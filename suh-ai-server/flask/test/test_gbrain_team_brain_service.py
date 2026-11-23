"""GbrainTeamBrainService·등록부·인스턴스: 만들기 흐름 (다시 실행해도 같은 결과), 기존 계정 비번 처리, 중간 실패 시 새 비번 전달, 헬스 (AI DB·서버 작업은 가짜)"""
import json

import pytest

from config import gbrain_server_config
from service.ai_db.ai_db_errors import PermissionDenied
from service.gbrain_instance import build_personal_instance, build_team_instance
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_brain_service import GbrainTeamBrainService
from service.gbrain_team_registry import GbrainTeamRegistry, GbrainTeamRegistryError

NEW_PASSWORD = 'new-writer-password-xyz'
GIVEN_PASSWORD = 'given-writer-password'


class FakeAiDbService:
    def __init__(self, databases=(), roles=(), is_ready=False, has_pages_table=False):
        self.databases = list(databases)
        self.roles = list(roles)
        self.is_ready = is_ready
        self.has_pages_table = has_pages_table
        self.calls = []

    def list_databases(self):
        return [{'name': name} for name in self.databases]

    def list_roles(self):
        return [{'name': name} for name in self.roles]

    def create_database(self, name, owner_role=None):
        self.calls.append(('create_database', name))
        self.databases.append(name)

    def create_role(self, name, database_name=None):
        self.calls.append(('create_role', name, database_name))
        self.roles.append(name)
        return {'name': name, 'password': NEW_PASSWORD}

    def get_gbrain_status(self, database_name):
        writer_role = database_name.replace('gbrain_', '') + '_writer' if self.is_ready else None
        return {'is_ready': self.is_ready, 'writer_role': writer_role, 'has_pages_table': self.has_pages_table}

    def prepare_gbrain(self, database_name, writer_role):
        self.calls.append(('prepare_gbrain', database_name, writer_role))
        self.is_ready = True


class FakeProvisioner:
    def __init__(self, has_config=False, fail_step=None):
        self.has_config = has_config
        self.fail_step = fail_step
        self.calls = []

    def _maybe_fail(self, step):
        if self.fail_step == step:
            raise GbrainServerError('명령 실패', f'{step}_failed', 500)

    def ensure_admin_token(self, instance):
        self.calls.append(('admin_token', instance.brain_id))
        return True

    def has_brain_config(self, instance):
        return self.has_config

    def build_database_url(self, instance, writer_password):
        return f'postgresql://{instance.writer_role}:{writer_password}@127.0.0.1:5433/{instance.database_name}'

    def write_brain_config(self, instance, database_url):
        self.calls.append(('write_config', database_url))
        self.has_config = True

    def initialize_new_brain(self, instance, database_url):
        self.calls.append(('init', database_url))
        self.has_config = True

    def install_service(self, instance):
        self._maybe_fail('service')
        self.calls.append(('install', instance.service_name, instance.port))

    def publish_nginx_route(self, instance):
        self._maybe_fail('nginx')
        self.calls.append(('nginx', instance.brain_id, instance.port))
        return True

    def get_nginx_map_path(self, instance):
        return f'/teams/nginx/{instance.brain_id}.map'


class FakeServerService:
    healthy_projects = set()

    def __init__(self, instance):
        self.instance = instance

    def get_status(self):
        is_healthy = self.instance.brain_id in self.healthy_projects
        return {'service_state': 'running', 'service_running': True, 'is_healthy': is_healthy,
                'version': '0.60.739.0', 'has_admin_token': True}

    def fetch_health(self):
        return {'status': 'ok'} if self.instance.brain_id in self.healthy_projects else None


@pytest.fixture
def team_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_TEAM_ROOT', str(tmp_path))
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_SECRETS_DIR', str(tmp_path / 'secrets'))
    return tmp_path


def build_service(ai_db_service, provisioner, team_root):
    return GbrainTeamBrainService(ai_db_service_factory=lambda: ai_db_service, registry=GbrainTeamRegistry(),
                                  provisioner=provisioner, server_service_factory=FakeServerService)


# ---------- 인스턴스 이름 규칙 ----------
def test_팀_인스턴스는_이름_규칙으로_서비스_폴더_공개주소_MCP이름을_정한다(team_root):
    instance = build_team_instance('passql', 3141, 'gbrain_passql', 'passql_writer')

    assert instance.service_name == 'gbrain-team-passql'
    assert instance.server_url == 'http://127.0.0.1:3141'
    assert instance.mcp_url == 'https://ai.suhsaechan.kr/team/passql/mcp'
    # 개인 gbrain 과 다른 MCP 이름 > Claude 도구 이름 mcp__gbrain-passql__* 로 분리
    assert instance.mcp_server_name == 'gbrain-passql'
    assert instance.default_scope_preset == 'read_only'
    assert instance.admin_token_file.endswith('gbrain-team-passql-admin-token')


def test_개인_인스턴스는_기존_gbrain_http_값을_그대로_쓴다():
    instance = build_personal_instance()

    assert (instance.service_name, instance.port, instance.mcp_server_name) == ('gbrain-http', 3131, 'gbrain')
    assert instance.mcp_url == 'https://ai.suhsaechan.kr/mcp' and instance.default_scope_preset == 'read_write'


# ---------- 등록부 ----------
def test_등록부는_가장_작은_빈_포트를_주고_다시_등록하면_포트를_유지한다(team_root):
    registry = GbrainTeamRegistry()

    first = registry.register('passql', 'gbrain_passql', 'passql_writer')
    second = registry.register('romrom', 'gbrain_romrom', 'romrom_writer')
    again = registry.register('passql', 'gbrain_passql', 'passql_writer')

    assert (first['port'], second['port'], again['port']) == (3141, 3142, 3141)
    assert [entry['project'] for entry in registry.list_entries()] == ['passql', 'romrom']
    saved = json.loads((team_root / 'team-brains.json').read_text(encoding='utf-8'))
    assert 'password' not in json.dumps(saved)


def test_등록부_파일이_깨지면_빈_목록이_아니라_오류다(team_root):
    (team_root / 'team-brains.json').write_text('{broken', encoding='utf-8')

    with pytest.raises(GbrainTeamRegistryError):
        GbrainTeamRegistry().list_entries()


# ---------- 만들기 ----------
def test_새_프로젝트는_DB_계정_준비_스키마_서비스_nginx_를_모두_만들고_새_비번을_1회_준다(team_root):
    ai_db_service, provisioner = FakeAiDbService(), FakeProvisioner()

    created = build_service(ai_db_service, provisioner, team_root).create_team_brain('romrom')

    assert ai_db_service.calls == [('create_database', 'gbrain_romrom'),
                                   ('create_role', 'romrom_writer', 'gbrain_romrom'),
                                   ('prepare_gbrain', 'gbrain_romrom', 'romrom_writer')]
    assert ('init', f'postgresql://romrom_writer:{NEW_PASSWORD}@127.0.0.1:5433/gbrain_romrom') in provisioner.calls
    assert ('install', 'gbrain-team-romrom', 3141) in provisioner.calls
    assert ('nginx', 'romrom', 3141) in provisioner.calls
    assert created['steps']['database'] == 'created' and created['steps']['config'] == 'initialized'
    assert created['writer_secret']['password'] == NEW_PASSWORD
    assert '127.0.0.1:15433/gbrain_romrom' in created['writer_secret']['sync_connection_url']
    assert created['brain']['mcp_server_name'] == 'gbrain-romrom'


def test_기존_브레인_passQL_은_데이터를_건드리지_않고_설정만_쓰고_마이그레이션만_한다(team_root):
    ai_db_service = FakeAiDbService(databases=['gbrain_passql'], roles=['passql_writer'],
                                    is_ready=True, has_pages_table=True)
    provisioner = FakeProvisioner()

    created = build_service(ai_db_service, provisioner, team_root).create_team_brain('passql', GIVEN_PASSWORD)

    # DB·계정 생성, 브레인 준비, 비번 재설정 없음
    assert ai_db_service.calls == []
    assert ('write_config', f'postgresql://passql_writer:{GIVEN_PASSWORD}@127.0.0.1:5433/gbrain_passql') in provisioner.calls
    assert not any(call[0] == 'init' for call in provisioner.calls)
    assert created['steps'] == {'database': 'kept', 'writer_role': 'kept', 'prepare': 'kept', 'admin_token': 'created',
                                'config': 'written', 'service': 'installed', 'nginx': 'published',
                                'monitoring': 'included'}
    assert 'writer_secret' not in created


def test_기존_계정인데_설정도_비번도_없으면_409_로_비번을_요청한다(team_root):
    ai_db_service = FakeAiDbService(databases=['gbrain_passql'], roles=['passql_writer'], is_ready=True,
                                    has_pages_table=True)

    with pytest.raises(GbrainServerError) as error_info:
        build_service(ai_db_service, FakeProvisioner(), team_root).create_team_brain('passql')

    assert (error_info.value.code, error_info.value.status_code) == ('writer_password_required', 409)


def test_다시_만들기는_설정을_유지하고_같은_포트로_서비스만_갱신한다(team_root):
    ai_db_service = FakeAiDbService(databases=['gbrain_passql'], roles=['passql_writer'], is_ready=True,
                                    has_pages_table=True)
    service = build_service(ai_db_service, FakeProvisioner(has_config=True), team_root)

    first = service.create_team_brain('passql')
    second = service.create_team_brain('passql')

    assert first['steps']['config'] == second['steps']['config'] == 'kept'
    assert first['brain']['port'] == second['brain']['port'] == 3141


def test_새_계정을_만든_뒤_서비스_설치가_실패해도_새_비번은_오류_응답에_실린다(team_root):
    provisioner = FakeProvisioner(fail_step='service')

    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeAiDbService(), provisioner, team_root).create_team_brain('romrom')

    assert error_info.value.code == 'service_failed'
    assert error_info.value.details['writer_secret']['password'] == NEW_PASSWORD
    assert error_info.value.details['steps']['config'] == 'initialized'


@pytest.mark.parametrize('project', ['', 'Passql', 'pass-ql', 'p', '1abc', 'a' * 21, None])
def test_프로젝트_키_규칙_밖이면_400(team_root, project):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeAiDbService(), FakeProvisioner(), team_root).create_team_brain(project)

    assert (error_info.value.code, error_info.value.status_code) == ('invalid_project', 400)


def test_예약어_personal_은_형식이_맞아도_이유를_따로_알린다(team_root):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeAiDbService(), FakeProvisioner(), team_root).create_team_brain('personal')

    assert (error_info.value.code, error_info.value.status_code) == ('reserved_project', 400)
    assert '개인 브레인' in str(error_info.value)


def test_AI_DB_오류는_같은_코드로_전달한다(team_root):
    ai_db_service = FakeAiDbService()

    def deny(*args, **kwargs):
        raise PermissionDenied()
    ai_db_service.create_database = deny

    with pytest.raises(GbrainServerError) as error_info:
        build_service(ai_db_service, FakeProvisioner(), team_root).create_team_brain('romrom')

    assert error_info.value.code == 'permission_denied'


# ---------- 헬스 ----------
def test_헬스는_등록된_팀_브레인이_전부_응답해야_정상이다(team_root):
    registry = GbrainTeamRegistry()
    registry.register('passql', 'gbrain_passql', 'passql_writer')
    registry.register('romrom', 'gbrain_romrom', 'romrom_writer')
    service = build_service(FakeAiDbService(), FakeProvisioner(), team_root)

    FakeServerService.healthy_projects = {'passql'}
    assert service.check_health() == {'is_healthy': False, 'unhealthy_projects': ['romrom']}
    FakeServerService.healthy_projects = {'passql', 'romrom'}
    assert service.check_health()['is_healthy'] is True


def test_없는_팀_브레인은_404(team_root):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeAiDbService(), FakeProvisioner(), team_root).find_instance('nothing')

    assert error_info.value.status_code == 404
