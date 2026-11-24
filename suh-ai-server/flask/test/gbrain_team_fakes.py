"""팀 브레인 시험 공통 가짜 (#226): 메모리 AI DB(검사·생성·권한·준비), 슈퍼유저 손보기, 서버 작업, 서비스 상태
지우는 호출(drop_*·delete_*)은 부르면 바로 실패 > 흐름 어디에도 삭제가 없음을 실행으로 확인
"""
from service.gbrain_server_service import GbrainServerError

NEW_PASSWORD = 'new-writer-password-xyz'
GIVEN_PASSWORD = 'given-writer-password'
ADMIN_ROLE = 'ai_db_admin'
# 변경 호출 이름 (dry_run 이 하나도 부르면 안 됨)
MUTATING_CALLS = frozenset({'create_team_database', 'create_team_writer_role', 'apply_team_writer_grants',
                            'prepare_gbrain', 'repair'})


def build_database(owner=ADMIN_ROLE, can_connect=True, has_ops_schema=True, writer_role=None, has_pages_table=False,
                   public_relation_count=0, extra_schemas=(), foreign_relation_owners=(), foreign_function_count=0):
    """검사 결과 모양 (writer_role 있으면 준비 끝난 gbrain DB)"""
    return {'exists': True, 'caller_role': ADMIN_ROLE, 'owner': owner, 'can_connect': can_connect,
            'is_inspected': can_connect, 'has_ops_schema': has_ops_schema, 'has_event_trigger': writer_role is not None,
            'rls_function_owner': writer_role, 'has_pages_table': has_pages_table,
            'extra_schemas': list(extra_schemas), 'public_relation_count': public_relation_count,
            'foreign_relation_owners': list(foreign_relation_owners), 'foreign_function_count': foreign_function_count}


def build_gbrain_database(writer_role):
    return build_database(writer_role=writer_role, has_pages_table=True, public_relation_count=188)


class NoDeleteMixin:
    """삭제 계열 호출 > 시험 실패"""

    def _refuse(self, name):
        raise AssertionError(f'team brain flow must not call {name}')

    def drop_database(self, *args, **kwargs):
        self._refuse('drop_database')

    def drop_role(self, *args, **kwargs):
        self._refuse('drop_role')

    def delete_database(self, *args, **kwargs):
        self._refuse('delete_database')

    def delete_role(self, *args, **kwargs):
        self._refuse('delete_role')

    def reset_password(self, *args, **kwargs):
        self._refuse('reset_password')

    def revoke(self, *args, **kwargs):
        self._refuse('revoke')


class FakeTeamAiDbService(NoDeleteMixin):
    """databases: 이름 > 검사 결과, roles: 이름 > 계정 검사 결과, fail_on: 실패시킬 호출 이름 > AiDbError"""

    def __init__(self, databases=None, roles=None, fail_on=None):
        self.databases = dict(databases or {})
        self.roles = dict(roles or {})
        self.fail_on = dict(fail_on or {})
        self.calls = []

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail_on:
            raise self.fail_on[name]

    def inspect_team_database(self, database_name, writer_role):
        self._record('inspect_team_database', database_name)
        return dict(self.databases.get(database_name) or {'exists': False})

    def inspect_team_writer_role(self, writer_role):
        self._record('inspect_team_writer_role', writer_role)
        return dict(self.roles.get(writer_role) or {'exists': False})

    def create_team_database(self, database_name):
        self._record('create_team_database', database_name)
        self.databases[database_name] = build_database()

    def create_team_writer_role(self, writer_role):
        self._record('create_team_writer_role', writer_role)
        self.roles[writer_role] = {'exists': True, 'can_login': True, 'is_superuser': False, 'is_managed': True}
        return NEW_PASSWORD

    def apply_team_writer_grants(self, database_name, writer_role):
        self._record('apply_team_writer_grants', database_name, writer_role)

    def prepare_gbrain(self, database_name, writer_role):
        self._record('prepare_gbrain', database_name, writer_role)
        self.databases[database_name] = {**self.databases[database_name], 'has_event_trigger': True,
                                         'rls_function_owner': writer_role}

    def get_gbrain_status(self, database_name):
        database = self.databases.get(database_name) or {}
        return {'is_ready': bool(database.get('has_event_trigger')), 'has_pages_table': database.get('has_pages_table'),
                'writer_role': database.get('rls_function_owner')}

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in MUTATING_CALLS]


def build_managed_role():
    return {'exists': True, 'can_login': True, 'is_superuser': False, 'is_managed': True}


class FakeDatabaseRepair(NoDeleteMixin):
    """슈퍼유저 손보기 가짜: 손본 뒤 AI DB 가짜의 검사 결과를 관리 계정 소유·ops 있음으로 바꿈"""

    def __init__(self, ai_db_service, superuser_inspection=None, error=None):
        self.ai_db_service = ai_db_service
        self.superuser_inspection = superuser_inspection
        self.error = error
        self.calls = []

    def inspect_team_database(self, database_name, writer_role):
        self.calls.append(('inspect', database_name))
        if self.error:
            raise self.error
        return dict(self.superuser_inspection)

    def repair(self, database_name, admin_role, repairs):
        self.calls.append(('repair', database_name, admin_role, tuple(repairs)))
        self.ai_db_service.calls.append(('repair', database_name))
        self.ai_db_service.databases[database_name] = {
            **(self.superuser_inspection or self.ai_db_service.databases[database_name]),
            'owner': admin_role, 'can_connect': True, 'is_inspected': True, 'has_ops_schema': True}


class FakeProvisioner:
    def __init__(self, has_config=False, fail_step=None, has_admin_token=False, is_nginx_published=False):
        self.has_config = has_config
        self.fail_step = fail_step
        self.admin_token_exists = has_admin_token
        self.is_nginx_published = is_nginx_published
        self.calls = []

    def _maybe_fail(self, step, code):
        if self.fail_step == step:
            raise GbrainServerError('서버 명령이 실패했어요', code, 500)

    def ensure_admin_token(self, instance):
        self.calls.append(('admin_token', instance.brain_id))
        created = not self.admin_token_exists
        self.admin_token_exists = True
        return created

    def has_admin_token(self, instance):
        return self.admin_token_exists

    def has_brain_config(self, instance):
        return self.has_config

    def build_database_url(self, instance, writer_password):
        return f'postgresql://{instance.writer_role}:{writer_password}@127.0.0.1:5433/{instance.database_name}'

    def write_brain_config(self, instance, database_url):
        self._maybe_fail('config', 'gbrain_migrate_failed')
        self.calls.append(('write_config', database_url))
        self.has_config = True

    def initialize_new_brain(self, instance, database_url):
        self._maybe_fail('config', 'gbrain_init_failed')
        self.calls.append(('init', database_url))
        self.has_config = True

    def install_service(self, instance):
        self._maybe_fail('service', 'service_install_failed')
        self.calls.append(('install', instance.service_name, instance.port))

    def publish_nginx_route(self, instance):
        self._maybe_fail('nginx', 'nginx_test_failed')
        self.calls.append(('nginx', instance.brain_id, instance.port))
        changed = not self.is_nginx_published
        self.is_nginx_published = True
        return changed

    def is_nginx_route_published(self, instance):
        return self.is_nginx_published

    def get_nginx_map_path(self, instance):
        return f'/teams/nginx/{instance.brain_id}.map'


class FakeServerService:
    healthy_projects = set()
    installed_services = set()

    def __init__(self, instance):
        self.instance = instance

    def get_status(self):
        is_healthy = self.instance.brain_id in self.healthy_projects
        state = 'running' if self.instance.service_name in self.installed_services else 'not_installed'
        return {'service_state': state, 'service_running': state == 'running', 'is_healthy': is_healthy,
                'version': '0.60.739.0', 'has_admin_token': True}

    def fetch_health(self):
        return {'status': 'ok'} if self.instance.brain_id in self.healthy_projects else None
