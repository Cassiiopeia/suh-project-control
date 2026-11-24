"""
팀 브레인 DB 단계 (#226): 검사 > 판정 > (슈퍼유저 손보기) > DB > 쓰기 계정 > 권한 재적용 > 브레인 준비
판정 4가지: 없음(만듦) / 빈 DB(받아 씀) / gbrain DB(그대로) / 알 수 없음(멈춤, 아무것도 지우지 않음)
쓰기 계정 비번은 새로 만들 때만 생성, 기존 계정 비번은 바꾸지 않음
"""
import logging
from dataclasses import dataclass, field

from service.ai_db.ai_db_errors import AiDbError
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_database_repair import REPAIR_OPS_INSTALL, REPAIR_OWNER_CHANGE

logger = logging.getLogger(__name__)

DATABASE_ABSENT = 'absent'
DATABASE_EMPTY = 'empty'
DATABASE_GBRAIN = 'gbrain'
DATABASE_UNKNOWN = 'unknown'

# dry_run 계획 값 (클라이언트 /pro-gbrain 계약)
PLAN_EXISTS = 'exists'
PLAN_WOULD_CREATE = 'would_create'
PLAN_WOULD_ADOPT = 'would_adopt'
PLAN_WOULD_REGRANT = 'would_regrant'
PLAN_REFUSE = 'refuse'
DATABASE_PLAN_BY_KIND = {DATABASE_ABSENT: PLAN_WOULD_CREATE, DATABASE_EMPTY: PLAN_WOULD_ADOPT,
                         DATABASE_GBRAIN: PLAN_EXISTS, DATABASE_UNKNOWN: PLAN_REFUSE}


def classify_team_database(inspection: dict) -> str:
    """검사 결과 > 판정 (안을 못 봤거나 쓰기 계정 것이 아닌 객체가 있으면 알 수 없음)"""
    if not inspection.get('exists'):
        return DATABASE_ABSENT
    if not inspection.get('is_inspected'):
        return DATABASE_UNKNOWN
    if (inspection.get('extra_schemas') or inspection.get('foreign_relation_owners')
            or inspection.get('foreign_function_count')):
        return DATABASE_UNKNOWN
    return DATABASE_GBRAIN if inspection.get('public_relation_count') else DATABASE_EMPTY


def list_required_repairs(inspection: dict, admin_role: str) -> list:
    """슈퍼유저 손보기 항목: 소유자가 관리 계정 아님, ai_db_ops 없음"""
    repairs = []
    if inspection.get('owner') != admin_role:
        repairs.append(REPAIR_OWNER_CHANGE)
    if not inspection.get('has_ops_schema'):
        repairs.append(REPAIR_OPS_INSTALL)
    return repairs


def is_prepared_for(inspection: dict, writer_role: str) -> bool:
    return bool(inspection.get('has_ops_schema') and inspection.get('has_event_trigger')
                and inspection.get('rls_function_owner') == writer_role)


@dataclass
class TeamDatabaseState:
    database_name: str
    writer_role: str
    database: dict
    writer: dict
    admin_role: str = None
    kind: str = DATABASE_ABSENT
    repairs: list = field(default_factory=list)
    blockers: list = field(default_factory=list)


class GbrainTeamDatabaseSteps:
    def __init__(self, ai_db_service, repair):
        self._ai_db_service = ai_db_service
        self._repair = repair

    # ---------- 검사 (읽기만) ----------
    def inspect(self, database_name: str, writer_role: str) -> TeamDatabaseState:
        """DB·쓰기 계정 검사 > 판정 > 손보기 항목·막는 이유 (관리 계정이 못 보는 DB 는 슈퍼유저로 봄)"""
        database = self._run_ai_db('team_database_inspect_failed', '팀 DB 를 살펴보지 못했어요',
                                   lambda: self._ai_db_service.inspect_team_database(database_name, writer_role))
        writer = self._run_ai_db('team_database_inspect_failed', '쓰기 계정을 살펴보지 못했어요',
                                 lambda: self._ai_db_service.inspect_team_writer_role(writer_role))
        state = TeamDatabaseState(database_name, writer_role, database, writer, admin_role=database.get('caller_role'))
        if database.get('exists') and not database.get('can_connect'):
            try:
                state.database = {**database, **self._repair.inspect_team_database(database_name, writer_role),
                                  'owner': database.get('owner')}
            except GbrainServerError as error:
                state.blockers.append(error)
        state.kind = classify_team_database(state.database)
        if state.kind in (DATABASE_EMPTY, DATABASE_GBRAIN):
            state.repairs = list_required_repairs(state.database, state.admin_role)
        state.blockers += self._find_blockers(state)
        return state

    # ---------- 실행 ----------
    def ensure_database(self, state: TeamDatabaseState) -> str:
        """없음 > 생성, 빈 DB > 받아 씀(adopted), gbrain DB > kept (손보기 필요하면 먼저)"""
        if state.kind == DATABASE_ABSENT:
            self._run_ai_db('team_database_create_failed', 'DB 를 만들지 못했어요',
                            lambda: self._ai_db_service.create_team_database(state.database_name))
            return 'created'
        if state.repairs:
            self._repair.repair(state.database_name, state.admin_role, state.repairs)
            self._verify_repaired(state)
        return 'adopted' if state.kind == DATABASE_EMPTY else 'kept'

    def ensure_writer_role(self, state: TeamDatabaseState):
        """없으면 생성 > 새 비번, 있으면 None (비번 그대로)"""
        if state.writer.get('exists'):
            return None
        return self._run_ai_db('team_writer_role_create_failed', '쓰기 계정을 만들지 못했어요',
                               lambda: self._ai_db_service.create_team_writer_role(state.writer_role))

    def apply_grants(self, state: TeamDatabaseState) -> str:
        self._run_ai_db('team_grant_failed', '쓰기 계정 권한을 적용하지 못했어요',
                        lambda: self._ai_db_service.apply_team_writer_grants(state.database_name, state.writer_role))
        return 'reapplied'

    def prepare(self, state: TeamDatabaseState) -> str:
        """확장·RLS 트리거·쓰기 계정 BYPASSRLS 매번 적용 (준비 함수가 있으면 건너뜀)"""
        was_prepared = is_prepared_for(state.database, state.writer_role)
        self._run_ai_db('team_prepare_failed', '브레인 준비를 하지 못했어요',
                        lambda: self._ai_db_service.prepare_gbrain(state.database_name, state.writer_role))
        return 'reapplied' if was_prepared else 'prepared'

    def has_pages_table(self, database_name: str) -> bool:
        status = self._run_ai_db('team_prepare_failed', '브레인 상태를 읽지 못했어요',
                                 lambda: self._ai_db_service.get_gbrain_status(database_name))
        return bool(status.get('has_pages_table'))

    # ---------- dry_run 계획 ----------
    @staticmethod
    def plan(state: TeamDatabaseState) -> dict:
        blocked_codes = {blocker.code for blocker in state.blockers}
        database_plan = DATABASE_PLAN_BY_KIND[state.kind]
        if state.kind == DATABASE_GBRAIN and state.repairs:
            database_plan = PLAN_WOULD_ADOPT
        is_writer_blocked = any(code.startswith('team_writer_role_') for code in blocked_codes)
        writer_plan = PLAN_REFUSE if is_writer_blocked else (
            PLAN_EXISTS if state.writer.get('exists') else PLAN_WOULD_CREATE)
        is_blocked = PLAN_REFUSE in (database_plan, writer_plan) or bool(blocked_codes)
        return {
            'database': database_plan, 'writer_role': writer_plan,
            'grants': PLAN_REFUSE if is_blocked else PLAN_WOULD_REGRANT,
            'prepare': PLAN_REFUSE if is_blocked else (
                PLAN_EXISTS if is_prepared_for(state.database, state.writer_role) else PLAN_WOULD_CREATE),
        }

    # ---------- 내부 ----------
    @staticmethod
    def _find_blockers(state: TeamDatabaseState) -> list:
        blockers = []
        if state.kind == DATABASE_UNKNOWN and state.database.get('is_inspected'):
            error = GbrainServerError(
                f'{state.database_name} DB 에 팀 브레인이 아닌 객체가 있어서 멈췄어요. 아무것도 지우지 않았어요',
                'team_database_not_empty_unknown', 409)
            error.details = {'found': {key: state.database.get(key) for key in (
                'owner', 'extra_schemas', 'foreign_relation_owners', 'foreign_function_count', 'public_relation_count')}}
            blockers.append(error)
        writer = state.writer
        if writer.get('exists') and writer.get('is_superuser'):
            blockers.append(GbrainServerError(f'{state.writer_role} 는 슈퍼유저라 쓰기 계정으로 쓸 수 없어요',
                                              'team_writer_role_protected', 409))
        elif writer.get('exists') and not writer.get('is_managed'):
            blockers.append(GbrainServerError(f'{state.writer_role} 계정을 관리 계정이 관리하지 않아서 멈췄어요',
                                              'team_writer_role_not_managed', 409))
        elif writer.get('exists') and not writer.get('can_login'):
            blockers.append(GbrainServerError(f'{state.writer_role} 계정이 로그인할 수 없어서 멈췄어요',
                                              'team_writer_role_cannot_login', 409))
        return blockers

    def _verify_repaired(self, state: TeamDatabaseState) -> None:
        """손보기 뒤 관리 계정으로 다시 검사: 소유자·접속·ops 확인 (안 되면 멈춤)"""
        database = self._run_ai_db('team_database_inspect_failed', '손본 DB 를 다시 살펴보지 못했어요',
                                   lambda: self._ai_db_service.inspect_team_database(state.database_name,
                                                                                    state.writer_role))
        if not (database.get('can_connect') and database.get('has_ops_schema')
                and database.get('owner') == state.admin_role):
            raise GbrainServerError('DB 를 손봤지만 관리 계정이 아직 쓸 수 없어요', 'team_database_repair_failed', 500)
        state.database = database

    @staticmethod
    def _run_ai_db(step_code: str, message: str, action):
        """AI 서버 DB 오류 > 단계 code (원인 AI DB code 는 cause), 접속 불가는 ai_db_unavailable 503"""
        try:
            return action()
        except AiDbError as error:
            logger.warning(f'[gbrain team] ai db step failed : {step_code} cause={error.code}')
            is_unavailable = error.code == 'ai_db_unavailable'
            team_error = GbrainServerError(f'{message} [{error.code}]',
                                           'ai_db_unavailable' if is_unavailable else step_code,
                                           503 if is_unavailable else 409)
            team_error.details = {'cause': error.code}
            raise team_error
