"""gbrain_team_router·토큰 브레인 선택: 목록·만들기(no-store, 감사에 비번 없음)·헬스 200/503·제어, 토큰 ?brain= (팀 기본 읽기 전용, MCP 이름 gbrain-<project>)"""
import pytest

from app import app as flask_app
from router import gbrain_team_router
from service import gbrain_token_service as token_module
from service.audit_service import AuditAction
from service.gbrain_instance import build_team_instance
from service.gbrain_server_service import GbrainServerError

WRITER_PASSWORD = 'writer-secret-value'
TOKEN_SECRET = 'gbrain_' + 't' * 40
TOKEN_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
PASSQL = build_team_instance('passql', 3141, 'gbrain_passql', 'passql_writer')


class FakeTeamBrainService:
    def __init__(self):
        self.create_error = None
        self.is_healthy = True
        self.created_with = None

    def list_team_brains(self):
        return [{'project': 'passql', 'port': 3141, 'mcp_server_name': 'gbrain-passql'}]

    def check_health(self):
        return {'is_healthy': self.is_healthy, 'unhealthy_projects': [] if self.is_healthy else ['passql']}

    def create_team_brain(self, project, writer_password=None):
        self.created_with = (project, writer_password)
        if self.create_error:
            raise self.create_error
        return {'brain': {'project': project, 'port': 3141}, 'steps': {'config': 'written'}}

    def find_instance(self, project):
        if project != 'passql':
            raise GbrainServerError('팀 브레인을 찾지 못했어요', 'team_brain_not_found', 404)
        return PASSQL

    def describe(self, instance):
        return {'project': instance.brain_id}


class FakeTokenService:
    def __init__(self):
        self.calls = []

    def list_tokens(self):
        return []

    def create_token(self, device_name, scope_preset):
        self.calls.append(('create', device_name, scope_preset))
        scopes = ['read'] if scope_preset == 'read_only' else ['read', 'write']
        return {'token': {'id': TOKEN_ID, 'name': device_name, 'scopes': scopes}, 'secret': TOKEN_SECRET}

    def revoke_token(self, token_id):
        self.calls.append(('revoke', token_id))
        return {'id': token_id, 'name': 'teammate-kim', 'scopes': ['read']}


@pytest.fixture
def team_service():
    fake = FakeTeamBrainService()
    gbrain_team_router.set_service_factory(lambda: fake)
    yield fake
    gbrain_team_router.set_service_factory(None)


@pytest.fixture
def team_token_service(monkeypatch):
    fake = FakeTokenService()
    monkeypatch.setattr(token_module, 'get_token_service_for', lambda instance: fake)
    return fake


@pytest.fixture
def audit_calls(monkeypatch):
    from util import audit_helper
    calls = []

    def fake_record(category, action, actor_ip, detail=None, **kwargs):
        calls.append({'category': category, 'action': action, 'detail': detail, 'success': kwargs.get('success')})
        return True
    monkeypatch.setattr(audit_helper.audit_service, 'record', fake_record)
    return calls


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as test_client:
        yield test_client


def test_목록은_no_store(client, team_service):
    response = client.get('/gbrain/teams')

    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert response.get_json()['brains'][0]['mcp_server_name'] == 'gbrain-passql'


def test_만들기는_비번을_감사에_남기지_않고_no_store(client, team_service, audit_calls):
    response = client.post('/gbrain/teams', json={'project': 'passql', 'writer_password': WRITER_PASSWORD})

    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert team_service.created_with == ('passql', WRITER_PASSWORD)
    assert audit_calls[0]['action'] == AuditAction.GBRAIN_TEAM_CREATE
    assert audit_calls[0]['detail']['has_writer_password'] is True
    assert WRITER_PASSWORD not in str(audit_calls)


def test_만들기_중간_실패는_단계와_새_비번을_응답에만_싣는다(client, team_service, audit_calls):
    error = GbrainServerError('서비스 설치 실패', 'service_install_failed', 500)
    error.details = {'steps': {'writer_role': 'created'}, 'writer_secret': {'password': WRITER_PASSWORD}}
    team_service.create_error = error

    response = client.post('/gbrain/teams', json={'project': 'romrom'})

    body = response.get_json()
    assert response.status_code == 500 and body['code'] == 'service_install_failed'
    assert body['writer_secret']['password'] == WRITER_PASSWORD
    assert audit_calls[0]['success'] is False and WRITER_PASSWORD not in str(audit_calls)


def test_헬스는_전부_정상이면_200_아니면_503(client, team_service):
    assert client.get('/gbrain/teams/health').status_code == 200
    team_service.is_healthy = False
    response = client.get('/gbrain/teams/health')
    assert response.status_code == 503 and response.get_json()['unhealthy_projects'] == ['passql']


def test_없는_팀_브레인_제어는_404_이고_감사_행위가_정해지지_않는다(client, team_service, audit_calls):
    response = client.post('/gbrain/teams/nothing/control/restart')

    assert response.status_code == 404 and audit_calls == []


def test_팀_브레인_재시작은_그_서비스를_제어하고_브레인을_감사에_남긴다(client, team_service, audit_calls, monkeypatch):
    from service.gbrain_server_service import GbrainServerService
    restarted = []
    monkeypatch.setattr(GbrainServerService, 'restart_service', lambda self: restarted.append(self.service_name) or True)

    response = client.post('/gbrain/teams/passql/control/restart')

    assert response.status_code == 200 and restarted == ['gbrain-team-passql']
    assert audit_calls[0]['action'] == AuditAction.GBRAIN_RESTART
    assert audit_calls[0]['detail'] == {'brain': 'passql', 'service_name': 'gbrain-team-passql'}


# ---------- 토큰 브레인 선택 ----------
def test_팀_브레인_토큰은_기본_읽기_전용이고_MCP_이름이_gbrain_프로젝트다(client, team_service, team_token_service, audit_calls):
    response = client.post('/gbrain/tokens', json={'name': 'teammate-kim', 'brain': 'passql'})

    body = response.get_json()
    assert response.status_code == 200
    assert team_token_service.calls == [('create', 'teammate-kim', 'read_only')]
    assert body['mcp_server_name'] == 'gbrain-passql'
    assert body['mcp_url'] == 'https://ai.suhsaechan.kr/team/passql/mcp'
    assert body['token']['scopes'] == ['read']
    assert audit_calls[0]['detail']['brain'] == 'passql' and TOKEN_SECRET not in str(audit_calls)


def test_팀_브레인_토큰_목록과_폐기는_그_브레인_서비스로_간다(client, team_service, team_token_service):
    listed = client.get('/gbrain/tokens?brain=passql').get_json()
    revoked = client.post(f'/gbrain/tokens/{TOKEN_ID}/revoke', json={'brain': 'passql'})

    assert listed['mcp_server_name'] == 'gbrain-passql' and listed['default_scope_preset'] == 'read_only'
    assert revoked.status_code == 200 and team_token_service.calls == [('revoke', TOKEN_ID)]


def test_없는_브레인_토큰_요청은_404(client, team_service, team_token_service):
    response = client.get('/gbrain/tokens?brain=nothing')

    assert response.status_code == 404 and response.get_json()['code'] == 'team_brain_not_found'
