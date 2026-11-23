"""
팀 브레인 만들기·조회 (#210): 프로젝트마다 DB·쓰기 계정·gbrain HTTP 서버·공개 경로 1벌
만들기 흐름 (다시 눌러도 같은 결과): 검증 > DB > 쓰기 계정 > 브레인 준비 > 등록(포트) > 관리자 토큰 >
  gbrain 설정·스키마 > NSSM 서비스 > nginx 경로 > 감시(통합 헬스, 자동 포함)
쓰기 계정 비번: 새로 만들 때만 응답 1회 (동기화 맥용), 기존 계정은 운영자 입력으로만 받음 (재설정하면 맥 동기화가 끊김)
"""
import logging
import re
from urllib.parse import quote

from config import gbrain_server_config as config
from service.ai_db.ai_db_errors import AiDbError
from service.gbrain_instance import PERSONAL_BRAIN_ID, to_team_database_name, to_team_writer_role
from service.gbrain_server_service import GbrainServerError, GbrainServerService
from service.gbrain_team_provisioner import gbrain_team_provisioner
from service.gbrain_team_registry import GbrainTeamRegistryError, gbrain_team_registry

logger = logging.getLogger(__name__)

PROJECT_PATTERN = re.compile(config.GBRAIN_TEAM_PROJECT_PATTERN)
# 팀 프로젝트 키로 쓸 수 없는 값 (개인 브레인 id 와 겹침)
RESERVED_PROJECT_KEYS = frozenset({PERSONAL_BRAIN_ID})
# 동기화 맥이 쓰는 SSH 터널 포트 (외부 5432 는 닫혀 있음, #201)
SYNC_TUNNEL_LOCAL_PORT = 15433


class GbrainTeamBrainService:
    def __init__(self, ai_db_service_factory, registry=gbrain_team_registry, provisioner=gbrain_team_provisioner,
                 server_service_factory=GbrainServerService.for_instance):
        self._ai_db_service_factory = ai_db_service_factory
        self.registry = registry
        self.provisioner = provisioner
        self._server_service_factory = server_service_factory

    # ---------- 조회 ----------
    def list_team_brains(self) -> list:
        """등록된 팀 브레인 + 서비스 상태·헬스 (비번 없음)"""
        return [self.describe(instance) for instance in self._list_instances()]

    def describe(self, instance) -> dict:
        status = self._server_service_factory(instance).get_status()
        return {
            'project': instance.brain_id, 'label': instance.label, 'service_name': instance.service_name,
            'port': instance.port, 'database_name': instance.database_name, 'writer_role': instance.writer_role,
            'mcp_url': instance.mcp_url, 'mcp_server_name': instance.mcp_server_name,
            'gbrain_home': instance.gbrain_home, 'nginx_map_path': self.provisioner.get_nginx_map_path(instance),
            'service_state': status.get('service_state'), 'service_running': status.get('service_running'),
            'is_healthy': status.get('is_healthy'), 'version': status.get('version'),
            'has_admin_token': status.get('has_admin_token'),
        }

    def find_instance(self, project):
        """팀 프로젝트 키 > GbrainInstance (없거나 형식 밖이면 404)"""
        if not isinstance(project, str) or not PROJECT_PATTERN.match(project):
            raise GbrainServerError('팀 브레인을 찾지 못했어요', 'team_brain_not_found', 404)
        instance = self._run_registry(lambda: self.registry.find_instance(project))
        if instance is None:
            raise GbrainServerError('팀 브레인을 찾지 못했어요', 'team_brain_not_found', 404)
        return instance

    def check_health(self) -> dict:
        """감시용: 등록된 팀 브레인 전부 /health 정상이면 is_healthy (0개도 정상)"""
        unhealthy_projects = [instance.brain_id for instance in self._list_instances()
                              if not self._server_service_factory(instance).fetch_health()]
        return {'is_healthy': not unhealthy_projects, 'unhealthy_projects': unhealthy_projects}

    # ---------- 만들기 ----------
    def create_team_brain(self, project, writer_password=None) -> dict:
        """만들기 흐름 전체 > {brain, steps, writer_secret(새 계정일 때만)}"""
        self._validate_project(project)
        database_name, writer_role = to_team_database_name(project), to_team_writer_role(project)
        steps = {}
        ai_db_service = self._ai_db_service_factory()

        steps['database'] = self._run_ai_db(lambda: self._ensure_database(ai_db_service, database_name))
        created_password = self._run_ai_db(lambda: self._ensure_writer_role(ai_db_service, writer_role, database_name))
        steps['writer_role'] = 'created' if created_password else 'kept'
        try:
            instance = self._provision(project, ai_db_service, database_name, writer_role,
                                       created_password or writer_password, steps)
        except GbrainServerError as error:
            # 새 쓰기 계정 비번은 다시 받을 수 없음 > 뒤 단계가 실패해도 오류 응답에 1회 실어 보냄
            error.details = {'steps': steps}
            if created_password:
                error.details['writer_secret'] = self._build_writer_secret_for(project, created_password)
            raise
        logger.info(f'[gbrain team] created : project={project} port={instance.port} '
                    + ' '.join(f'{name}={value}' for name, value in steps.items()))

        result = {'brain': self.describe(instance), 'steps': steps}
        if created_password:
            result['writer_secret'] = self._build_writer_secret(instance, created_password)
        return result

    def _provision(self, project, ai_db_service, database_name, writer_role, writer_password, steps):
        """브레인 준비 > 등록(포트) > 관리자 토큰 > 설정·스키마 > 서비스 > nginx (steps 에 단계별 결과 기록)"""
        steps['prepare'] = self._run_ai_db(lambda: self._ensure_prepared(ai_db_service, database_name, writer_role))
        has_pages_table = self._run_ai_db(lambda: ai_db_service.get_gbrain_status(database_name)).get('has_pages_table')
        entry = self._run_registry(lambda: self.registry.register(project, database_name, writer_role))
        instance = self.registry.to_instance(entry)
        steps['admin_token'] = 'created' if self.provisioner.ensure_admin_token(instance) else 'kept'
        steps['config'] = self._ensure_brain_config(instance, writer_password, has_pages_table)
        self.provisioner.install_service(instance)
        steps['service'] = 'installed'
        steps['nginx'] = 'published' if self.provisioner.publish_nginx_route(instance) else 'kept'
        steps['monitoring'] = 'included'  # services.yml gbrain-team-brains 가 /gbrain/teams/health 로 전체 감시
        return instance

    # ---------- 단계 ----------
    @staticmethod
    def _ensure_database(ai_db_service, database_name) -> str:
        if any(database['name'] == database_name for database in ai_db_service.list_databases()):
            return 'kept'
        ai_db_service.create_database(database_name)
        return 'created'

    @staticmethod
    def _ensure_writer_role(ai_db_service, writer_role, database_name):
        """없으면 만들고 접속 권한까지 > 새 비번 반환, 있으면 None (비번 재설정 안 함)"""
        if any(role['name'] == writer_role for role in ai_db_service.list_roles()):
            return None
        return ai_db_service.create_role(writer_role, database_name)['password']

    @staticmethod
    def _ensure_prepared(ai_db_service, database_name, writer_role) -> str:
        gbrain_status = ai_db_service.get_gbrain_status(database_name)
        if gbrain_status.get('is_ready') and gbrain_status.get('writer_role') == writer_role:
            return 'kept'
        ai_db_service.prepare_gbrain(database_name, writer_role)
        return 'prepared'

    def _ensure_brain_config(self, instance, writer_password, has_pages_table) -> str:
        """설정 있음 + 새 비번 없음 > 유지, 비번 없이 설정도 없음 > 409 (기존 쓰기 계정 비번 입력 필요)"""
        has_config = self.provisioner.has_brain_config(instance)
        if has_config and not writer_password:
            return 'kept'
        if not writer_password:
            raise GbrainServerError(
                f'{instance.writer_role} 계정이 이미 있어요. 그 계정 비밀번호를 입력해 주세요 (동기화 맥의 설정에 있어요)',
                'writer_password_required', 409)
        database_url = self.provisioner.build_database_url(instance, writer_password)
        if has_pages_table:
            self.provisioner.write_brain_config(instance, database_url)
            return 'written'
        self.provisioner.initialize_new_brain(instance, database_url)
        return 'initialized'

    @staticmethod
    def _build_writer_secret(instance, password) -> dict:
        return GbrainTeamBrainService._build_writer_secret_for(instance.brain_id, password)

    @staticmethod
    def _build_writer_secret_for(project, password) -> dict:
        """동기화 맥용 1회 표시: SSH 터널 127.0.0.1:15433 기준 연결 문자열"""
        writer_role, database_name = to_team_writer_role(project), to_team_database_name(project)
        return {
            'name': writer_role, 'database': database_name, 'password': password,
            'sync_connection_url': (f'postgresql://{writer_role}:{quote(password, safe="")}@127.0.0.1:'
                                    f'{SYNC_TUNNEL_LOCAL_PORT}/{database_name}?sslmode=require'),
        }

    # ---------- 내부 ----------
    @staticmethod
    def _validate_project(project) -> None:
        if not isinstance(project, str) or not PROJECT_PATTERN.match(project):
            raise GbrainServerError('프로젝트 키는 영어 소문자로 시작하는 소문자·숫자 2~20자로 써 주세요 (예: passql)',
                                    'invalid_project', 400)
        # 형식은 맞지만 예약어 > 이유를 따로 알림
        if project in RESERVED_PROJECT_KEYS:
            raise GbrainServerError(f'"{project}" 키는 개인 브레인 이름이라 팀 브레인 키로 쓸 수 없어요. 다른 키를 써 주세요',
                                    'reserved_project', 400)

    def _list_instances(self) -> list:
        return self._run_registry(self.registry.list_instances)

    @staticmethod
    def _run_registry(action):
        try:
            return action()
        except GbrainTeamRegistryError as error:
            logger.error(f'[gbrain team] registry failed : {error}')
            raise GbrainServerError('팀 브레인 등록부를 읽지 못했어요', 'team_registry_unreadable', 500)

    @staticmethod
    def _run_ai_db(action):
        """AI 서버 DB 오류 > 같은 code 로 전달 (화면이 기존 AI DB 오류 코드로 원인 구분)"""
        try:
            return action()
        except AiDbError as error:
            logger.warning(f'[gbrain team] ai db step failed : {error.code}')
            raise GbrainServerError(f'AI 서버 DB 작업이 실패했어요 [{error.code}]', error.code,
                                    503 if error.code == 'ai_db_unavailable' else 409)
