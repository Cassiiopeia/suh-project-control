"""GbrainTeamBrainService·등록부·인스턴스: 만들기 흐름 (다시 실행해도 같은 결과), 기존 계정 비번 처리, 중간 실패 시 새 비번 전달, 헬스 (AI DB·서버 작업은 가짜)"""
import json

import pytest

from config import gbrain_server_config
from service.ai_db.ai_db_errors import PermissionDenied
from service.gbrain_instance import build_personal_instance, build_team_instance
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_brain_service import GbrainTeamBrainService
from service.gbrain_team_registry import GbrainTeamRegistry, GbrainTeamRegistryError
from gbrain_team_fakes import (
    GIVEN_PASSWORD, NEW_PASSWORD, FakeDatabaseRepair, FakeProvisioner, FakeServerService, FakeTeamAiDbService,
    build_gbrain_database, build_managed_role,
)


@pytest.fixture
def team_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_TEAM_ROOT', str(tmp_path))
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_SECRETS_DIR', str(tmp_path / 'secrets'))
    return tmp_path


def build_service(ai_db_service, provisioner, team_root, repair=None):
    return GbrainTeamBrainService(ai_db_service_factory=lambda: ai_db_service, registry=GbrainTeamRegistry(),
                                  provisioner=provisioner, server_service_factory=FakeServerService,
                                  database_repair=repair or FakeDatabaseRepair(ai_db_service))


def build_passql_ai_db():
    return FakeTeamAiDbService(databases={'gbrain_passql': build_gbrain_database('passql_writer')},
                               roles={'passql_writer': build_managed_role()})


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
def test_새_프로젝트는_DB_계정_권한_준비_스키마_서비스_nginx_를_모두_만들고_새_비번을_1회_준다(team_root):
    ai_db_service, provisioner = FakeTeamAiDbService(), FakeProvisioner()

    created = build_service(ai_db_service, provisioner, team_root).create_team_brain('romrom')

    assert ai_db_service.mutating_calls() == [('create_team_database', 'gbrain_romrom'),
                                              ('create_team_writer_role', 'romrom_writer'),
                                              ('apply_team_writer_grants', 'gbrain_romrom', 'romrom_writer'),
                                              ('prepare_gbrain', 'gbrain_romrom', 'romrom_writer')]
    assert ('init', f'postgresql://romrom_writer:{NEW_PASSWORD}@127.0.0.1:5433/gbrain_romrom') in provisioner.calls
    assert ('install', 'gbrain-team-romrom', 3141) in provisioner.calls
    assert ('nginx', 'romrom', 3141) in provisioner.calls
    assert created['steps']['database'] == 'created' and created['steps']['config'] == 'initialized'
    assert created['steps']['grants'] == 'reapplied' and created['steps']['prepare'] == 'prepared'
    assert created['writer_secret']['password'] == NEW_PASSWORD
    assert '127.0.0.1:15433/gbrain_romrom' in created['writer_secret']['sync_connection_url']
    assert created['brain']['mcp_server_name'] == 'gbrain-romrom'


def test_기존_브레인_passQL_은_데이터를_건드리지_않고_권한만_다시_주고_설정을_쓴다(team_root):
    ai_db_service, provisioner = build_passql_ai_db(), FakeProvisioner()

    created = build_service(ai_db_service, provisioner, team_root).create_team_brain('passql', GIVEN_PASSWORD)

    # DB·계정 생성·비번 재설정 없음, 권한·준비는 다시 적용
    assert ai_db_service.mutating_calls() == [('apply_team_writer_grants', 'gbrain_passql', 'passql_writer'),
                                              ('prepare_gbrain', 'gbrain_passql', 'passql_writer')]
    assert ('write_config', f'postgresql://passql_writer:{GIVEN_PASSWORD}@127.0.0.1:5433/gbrain_passql') in provisioner.calls
    assert not any(call[0] == 'init' for call in provisioner.calls)
    assert created['steps'] == {'database': 'kept', 'writer_role': 'kept', 'grants': 'reapplied',
                                'prepare': 'reapplied', 'admin_token': 'created', 'config': 'written',
                                'service': 'installed', 'nginx': 'published', 'monitoring': 'included'}
    assert 'writer_secret' not in created


def test_기존_계정인데_설정도_비번도_없으면_409_로_비번을_요청하고_다음_할_일을_싣는다(team_root):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(build_passql_ai_db(), FakeProvisioner(), team_root).create_team_brain('passql')

    error = error_info.value
    assert (error.code, error.status_code) == ('writer_password_required', 409)
    assert error.details['failed_step'] == 'config' and 'writer_password' in error.details['next_step']
    assert error.details['steps']['grants'] == 'reapplied'


def test_다시_만들기는_권한을_매번_다시_주고_비번을_바꾸지_않으며_같은_포트를_쓴다(team_root):
    ai_db_service = build_passql_ai_db()
    service = build_service(ai_db_service, FakeProvisioner(has_config=True), team_root)

    first = service.create_team_brain('passql')
    second = service.create_team_brain('passql')

    grant_calls = [call for call in ai_db_service.calls if call[0] == 'apply_team_writer_grants']
    assert len(grant_calls) == 2
    assert not any(call[0] == 'create_team_writer_role' for call in ai_db_service.calls)
    assert first['steps']['config'] == second['steps']['config'] == 'kept'
    assert second['steps']['grants'] == 'reapplied' and 'writer_secret' not in second
    assert first['brain']['port'] == second['brain']['port'] == 3141


def test_새_계정을_만든_뒤_서비스_설치가_실패해도_새_비번과_단계와_다음_할_일이_오류에_실린다(team_root):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeTeamAiDbService(), FakeProvisioner(fail_step='service'), team_root).create_team_brain('romrom')

    details = error_info.value.details
    assert error_info.value.code == 'service_install_failed'
    assert details['writer_secret']['password'] == NEW_PASSWORD
    assert details['steps']['config'] == 'initialized' and details['failed_step'] == 'service'
    assert details['next_step']


@pytest.mark.parametrize('project', ['', 'Passql', 'pass-ql', 'p', '1abc', 'a' * 21, None])
def test_프로젝트_키_규칙_밖이면_400(team_root, project):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeTeamAiDbService(), FakeProvisioner(), team_root).create_team_brain(project)

    assert (error_info.value.code, error_info.value.status_code) == ('invalid_project', 400)
    assert error_info.value.details['steps'] == {} and error_info.value.details['next_step']


def test_예약어_personal_은_형식이_맞아도_이유를_따로_알린다(team_root):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeTeamAiDbService(), FakeProvisioner(), team_root).create_team_brain('personal')

    assert (error_info.value.code, error_info.value.status_code) == ('reserved_project', 400)
    assert '개인 브레인' in str(error_info.value)


def test_AI_DB_오류는_단계_코드와_원인_코드로_전달한다(team_root):
    ai_db_service = FakeTeamAiDbService(fail_on={'create_team_database': PermissionDenied()})

    with pytest.raises(GbrainServerError) as error_info:
        build_service(ai_db_service, FakeProvisioner(), team_root).create_team_brain('romrom')

    error = error_info.value
    assert (error.code, error.details['cause'], error.details['failed_step']) == (
        'team_database_create_failed', 'permission_denied', 'database')
    assert error.details['steps'] == {} and error.details['next_step']


# ---------- 헬스 ----------
def test_헬스는_등록된_팀_브레인이_전부_응답해야_정상이다(team_root):
    registry = GbrainTeamRegistry()
    registry.register('passql', 'gbrain_passql', 'passql_writer')
    registry.register('romrom', 'gbrain_romrom', 'romrom_writer')
    service = build_service(FakeTeamAiDbService(), FakeProvisioner(), team_root)

    FakeServerService.healthy_projects = {'passql'}
    assert service.check_health() == {'is_healthy': False, 'unhealthy_projects': ['romrom']}
    FakeServerService.healthy_projects = {'passql', 'romrom'}
    assert service.check_health()['is_healthy'] is True


def test_없는_팀_브레인은_404(team_root):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeTeamAiDbService(), FakeProvisioner(), team_root).find_instance('nothing')

    assert error_info.value.status_code == 404
