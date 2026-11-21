"""gbrain_router: 상태·로그·제어·관리자 로그인·게이트 (서비스는 가짜, 감사 기록은 캡처)"""
import pytest

from app import app as flask_app
from config.gbrain_server_config import GBRAIN_ADMIN_GATE_COOKIE_NAME
from service import gbrain_server_service as service_module
from service.audit_service import AuditAction, AuditCategory
from service.gbrain_server_service import GbrainServerError

LOGIN_PATH = '/admin/auth/' + 'cd' * 32
GATE_COOKIE_VALUE = '1800000000.signature'


class FakeGbrainServer:
    def __init__(self):
        self.calls = []
        self.is_control_ok = True
        self.login_error = None
        self.log_error = None

    def get_status(self):
        return {'service_state': 'running', 'service_running': True, 'is_healthy': True, 'version': '0.60.739.0'}

    def read_logs(self, lines):
        if self.log_error:
            raise self.log_error
        self.calls.append(('logs', lines))
        return ['a', 'b']

    def start_service(self):
        self.calls.append(('start',))
        return self.is_control_ok

    def stop_service(self):
        self.calls.append(('stop',))
        return self.is_control_ok

    def restart_service(self):
        self.calls.append(('restart',))
        return self.is_control_ok

    def create_admin_login(self):
        if self.login_error:
            raise self.login_error
        return {'login_path': LOGIN_PATH, 'gate_cookie_value': GATE_COOKIE_VALUE, 'gate_valid_seconds': 43200}

    @staticmethod
    def is_admin_gate_valid(cookie_value):
        return cookie_value == GATE_COOKIE_VALUE


@pytest.fixture
def fake_server(monkeypatch):
    fake = FakeGbrainServer()
    monkeypatch.setattr(service_module, 'gbrain_server_service', fake)
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


def test_상태_조회(client, fake_server):
    response = client.get('/gbrain/status')
    assert response.status_code == 200
    assert response.get_json()['version'] == '0.60.739.0'


def test_로그_줄_수가_정수가_아니면_400(client, fake_server):
    assert client.get('/gbrain/logs?lines=abc').status_code == 400
    assert client.get('/gbrain/logs?lines=50').get_json()['logs'] == ['a', 'b']
    assert fake_server.calls == [('logs', 50)]


def test_로그_파일_없음은_404_코드로(client, fake_server):
    fake_server.log_error = GbrainServerError('x', 'log_unreadable', 404)
    response = client.get('/gbrain/logs')
    assert response.status_code == 404 and response.get_json()['code'] == 'log_unreadable'


@pytest.mark.parametrize('action, audit_action', [
    ('start', AuditAction.GBRAIN_START),
    ('stop', AuditAction.GBRAIN_STOP),
    ('restart', AuditAction.GBRAIN_RESTART),
])
def test_제어는_감사_기록을_남긴다(client, fake_server, audit_calls, action, audit_action):
    response = client.post(f'/gbrain/control/{action}', json={})
    assert response.status_code == 200
    assert fake_server.calls == [(action,)]
    assert audit_calls[0]['category'] == AuditCategory.GBRAIN
    assert audit_calls[0]['action'] == audit_action and audit_calls[0]['success'] is True


def test_제어_실패는_500과_실패_감사(client, fake_server, audit_calls):
    fake_server.is_control_ok = False
    assert client.post('/gbrain/control/restart', json={}).status_code == 500
    assert audit_calls[0]['success'] is False


def test_모르는_제어는_400이고_감사하지_않는다(client, fake_server, audit_calls):
    assert client.post('/gbrain/control/delete', json={}).status_code == 400
    assert audit_calls == []


def test_관리자_로그인은_경로와_게이트_쿠키를_주고_감사에_경로를_남기지_않는다(client, fake_server, audit_calls):
    response = client.post('/gbrain/admin-login', json={})

    assert response.status_code == 200
    assert response.get_json()['login_path'] == LOGIN_PATH
    set_cookie = response.headers['Set-Cookie']
    assert set_cookie.startswith(f'{GBRAIN_ADMIN_GATE_COOKIE_NAME}={GATE_COOKIE_VALUE}')
    for cookie_attribute in ('HttpOnly', 'Secure', 'SameSite=Strict', 'Path=/', 'Max-Age=43200'):
        assert cookie_attribute in set_cookie
    assert audit_calls[0]['action'] == AuditAction.GBRAIN_ADMIN_LOGIN
    assert LOGIN_PATH not in str(audit_calls[0]) and GATE_COOKIE_VALUE not in str(audit_calls[0])


def test_관리자_로그인_실패는_코드와_상태를_그대로_쿠키는_없음(client, fake_server, audit_calls):
    fake_server.login_error = GbrainServerError('x', 'admin_token_missing', 503)
    response = client.post('/gbrain/admin-login', json={})
    assert response.status_code == 503 and response.get_json()['code'] == 'admin_token_missing'
    assert 'Set-Cookie' not in response.headers
    assert audit_calls[0]['success'] is False


def test_게이트는_유효한_쿠키만_204(client, fake_server):
    assert client.get('/gbrain/admin-gate').status_code == 401
    client.set_cookie(GBRAIN_ADMIN_GATE_COOKIE_NAME, 'forged')
    assert client.get('/gbrain/admin-gate').status_code == 401
    client.set_cookie(GBRAIN_ADMIN_GATE_COOKIE_NAME, GATE_COOKIE_VALUE)
    assert client.get('/gbrain/admin-gate').status_code == 204


def test_관리_페이지_렌더(client):
    response = client.get('/admin/gbrain')
    assert response.status_code == 200
    assert 'gbrain.js' in response.get_data(as_text=True)
