"""
이미 있는 팀 DB 손보기 (#226): 관리 계정(ai_db_admin)이 못 하는 일 2개만 슈퍼유저로
  1) DB 소유자 > ai_db_admin (접속·public 스키마 권한 위임 가능하게)  2) ai_db_ops 준비 함수 설치 (sql/ai_db_ops_gbrain.sql)
빈 DB·gbrain DB 로 판정된 뒤에만 호출, 지우거나 비우는 일 없음, 슈퍼유저 접속 문자열은 로그·응답에 넣지 않음
"""
import logging

import psycopg2

from config import gbrain_server_config as config
from service.ai_db.ai_db_errors import AiDbError
from service.ai_db.pg_admin_client import PgAdminClient
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_provisioner import gbrain_team_provisioner

logger = logging.getLogger(__name__)

# 손보기 항목 이름 (steps.database_repair 값, dry_run details.database_repairs 값)
REPAIR_OWNER_CHANGE = 'owner_changed'
REPAIR_OPS_INSTALL = 'ops_installed'


def build_default_superuser_client() -> PgAdminClient:
    """개인 브레인 설정의 슈퍼유저 DSN 으로 같은 PG 클라이언트 (접속은 호출 때만)"""
    return PgAdminClient(gbrain_team_provisioner.read_personal_database_url(), connect=psycopg2.connect)


class GbrainTeamDatabaseRepair:
    def __init__(self, superuser_client_factory=build_default_superuser_client, ops_sql_path=None):
        self._superuser_client_factory = superuser_client_factory
        self._ops_sql_path = ops_sql_path

    def inspect_team_database(self, database_name: str, writer_role: str) -> dict:
        """관리 계정이 접속 못 하는 DB 를 슈퍼유저로 검사 (카탈로그만)"""
        return self._run(lambda client: client.inspect_team_database(database_name, writer_role),
                         'team_database_repair_unavailable', '이미 있는 DB 를 슈퍼유저로 살펴보지 못했어요')

    def repair(self, database_name: str, admin_role: str, repairs: list) -> None:
        """소유자 변경 > ops 설치 (판정에서 필요하다고 나온 것만)"""
        script_text = self._read_ops_script() if REPAIR_OPS_INSTALL in repairs else None

        def apply(client):
            if REPAIR_OWNER_CHANGE in repairs:
                client.change_team_database_owner(database_name, admin_role)
            if script_text is not None:
                client.run_sql_script(database_name, script_text)
        self._run(apply, 'team_database_repair_failed', '이미 있는 DB 를 팀 브레인용으로 손보지 못했어요')
        logger.info(f'[gbrain team] database repaired : {database_name} {"+".join(repairs)}')

    def _read_ops_script(self) -> str:
        path = self._ops_sql_path or config.GBRAIN_TEAM_OPS_SQL_PATH
        try:
            with open(path, encoding='utf-8') as script_stream:
                return script_stream.read()
        except OSError:
            raise GbrainServerError(f'DB 준비 함수 파일({config.GBRAIN_TEAM_OPS_SQL_DISPLAY_PATH})을 읽지 못했어요',
                                    'team_database_repair_unavailable', 500)

    def _run(self, action, error_code: str, message: str):
        """슈퍼유저 클라이언트 > 작업, 설정 없음·접속 실패·SQL 실패 > 같은 code 로 (원인은 cause)"""
        try:
            client = self._superuser_client_factory()
        except GbrainServerError as error:
            raise self._build_error(f'{message} (슈퍼유저 접속 정보 없음)', 'team_database_repair_unavailable',
                                    error.code)
        try:
            return action(client)
        except AiDbError as error:
            logger.warning(f'[gbrain team] superuser step failed : {error_code} cause={error.code}')
            unavailable = error.code == 'ai_db_unavailable'
            raise self._build_error(message, 'team_database_repair_unavailable' if unavailable else error_code,
                                    error.code)

    @staticmethod
    def _build_error(message: str, code: str, cause: str) -> GbrainServerError:
        error = GbrainServerError(f'{message} [{cause}]', code, 409 if code == 'team_database_repair_unavailable' else 500)
        error.details = {'cause': cause}
        return error
