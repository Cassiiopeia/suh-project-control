"""gbrain_token_router: 목록·발급·폐기, no-store, 감사 기록에 원문 없음 (서비스는 가짜, 감사 기록은 캡처)"""
import pytest

from app import app as flask_app
from service import gbrain_token_service as service_module
from service.audit_service import AuditAction, AuditCategory
from service.gbrain_server_service import GbrainServerError

SECRET = 'gbrain_' + 's' * 40
TOKEN_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


class FakeTokenService:
    def __init__(self):
        self.calls = []
        self.error = None

    def list_tokens(self):
        if self.error:
            raise self.error
        return [{'id': TOKEN_ID, 'name': 'work-macbook', 'scopes': ['read', 'write'], 'is_active': True}]

    def create_token(self, device_name, scope_preset):
        self.calls.append(('create', device_name, scope_preset))
        if self.error:
            raise self.error
        return {'token': {'id': TOKEN_ID, 'name': device_name, 'scopes': ['read', 'write']}, 'secret': SECRET}

    def revoke_token(self, token_id):
        self.calls.append(('revoke', token_id))
        if self.error:
            raise self.error
        return {'id': token_id, 'name': 'work-macbook', 'scopes': ['read', 'write']}


@pytest.fixture
def fake_service(monkeypatch):
    fake = FakeTokenService()
    monkeypatch.setattr(service_module, 'gbrain_token_service', fake)
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


def test_목록은_공개_MCP_주소와_함께_no_store(client, fake_service):
    response = client.get('/gbrain/tokens')
    body = response.get_json()
    assert response.status_code == 200
    assert body['tokens'][0]['id'] == TOKEN_ID and body['mcp_url'] == 'https://ai.suhsaechan.kr/mcp'
    assert response.headers['Cache-Control'] == 'no-store'


def test_목록_실패는_코드와_상태를_그대로(client, fake_service):
    fake_service.error = GbrainServerError('x', 'admin_token_missing', 503)
    response = client.get('/gbrain/tokens')
    assert response.status_code == 503 and response.get_json()['code'] == 'admin_token_missing'


def test_발급은_원문을_응답에만_싣고_감사에는_남기지_않는다(client, fake_service, audit_calls):
    response = client.post('/gbrain/tokens', json={'name': 'work-macbook', 'scope_preset': 'read_write'})

    assert response.status_code == 200
    assert response.get_json()['secret'] == SECRET
    assert response.headers['Cache-Control'] == 'no-store'
    assert fake_service.calls == [('create', 'work-macbook', 'read_write')]
    assert audit_calls[0]['category'] == AuditCategory.GBRAIN
    assert audit_calls[0]['action'] == AuditAction.GBRAIN_TOKEN_CREATE and audit_calls[0]['success'] is True
    assert audit_calls[0]['detail'] == {'name': 'work-macbook', 'scope_preset': 'read_write',
                                        'token_id': TOKEN_ID, 'scopes': ['read', 'write']}
    assert SECRET not in str(audit_calls)


def test_권한을_안_고르면_읽기_쓰기(client, fake_service, audit_calls):
    client.post('/gbrain/tokens', json={'name': 'work-macbook'})
    assert fake_service.calls == [('create', 'work-macbook', 'read_write')]


def test_발급_실패도_감사에_남는다(client, fake_service, audit_calls):
    fake_service.error = GbrainServerError('x', 'invalid_name', 400)
    response = client.post('/gbrain/tokens', json={'name': 'BAD'})
    assert response.status_code == 400 and response.get_json()['code'] == 'invalid_name'
    assert audit_calls[0]['success'] is False and audit_calls[0]['detail']['name'] == 'BAD'


def test_폐기는_id_로_하고_감사에_이름을_남긴다(client, fake_service, audit_calls):
    response = client.post(f'/gbrain/tokens/{TOKEN_ID}/revoke', json={})

    assert response.status_code == 200 and response.get_json()['token']['name'] == 'work-macbook'
    assert fake_service.calls == [('revoke', TOKEN_ID)]
    assert audit_calls[0]['action'] == AuditAction.GBRAIN_TOKEN_REVOKE
    assert audit_calls[0]['detail'] == {'token_id': TOKEN_ID, 'name': 'work-macbook', 'scopes': ['read', 'write']}


def test_없는_토큰_폐기는_404와_실패_감사(client, fake_service, audit_calls):
    fake_service.error = GbrainServerError('x', 'token_not_found', 404)
    assert client.post(f'/gbrain/tokens/{TOKEN_ID}/revoke', json={}).status_code == 404
    assert audit_calls[0]['success'] is False


def test_토큰_조회_수정은_GET_POST_외_메서드를_받지_않는다(client, fake_service):
    assert client.delete(f'/gbrain/tokens/{TOKEN_ID}/revoke').status_code == 405
    assert client.get(f'/gbrain/tokens/{TOKEN_ID}/revoke').status_code == 405
