"""sunshine_router 단위 테스트 — 서비스 계층은 가짜 객체로 대체, 감사 기록은 캡처"""
import pytest

from app import app as flask_app
from router import sunshine_router
from service import sunshine_service as svc_module
from service.audit_service import AuditAction, AuditCategory
from service.sunshine_service import SunshineApiError


class FakeSunshine:
    def __init__(self):
        self.calls = []
        self.fail = None          # SunshineApiError 를 던지게 할 때
        self.control_ok = True

    def _maybe_fail(self):
        if self.fail:
            raise self.fail

    def get_status(self):
        return {'service_running': True, 'api_reachable': True, 'credentials_configured': True,
                'stream_state': 'BUSY', 'current_app_id': '881448767', 'current_app_name': 'Desktop',
                'host_name': 'SUH-PROJECT-AI', 'version': '7.1.431.-1', 'public_host': 'h'}

    def list_clients(self):
        self._maybe_fail()
        return [{'name': 'SUH-MAC-PC', 'uuid': 'CA18CAF8-527F-5908-7D91-D9B5D498DC29'}]

    def unpair_client(self, uuid):
        self._maybe_fail()
        self.calls.append(('unpair', uuid))

    def submit_pin(self, pin, name):
        self._maybe_fail()
        self.calls.append(('pin', pin, name))

    def close_session(self):
        self._maybe_fail()
        self.calls.append(('close',))

    def read_logs(self, lines):
        self._maybe_fail()
        return ['a', 'b'][-lines:]

    def start_service(self):
        self.calls.append(('start',))
        return self.control_ok

    def stop_service(self):
        self.calls.append(('stop',))
        return self.control_ok

    def restart_service(self):
        self.calls.append(('restart',))
        return self.control_ok


@pytest.fixture
def fake(monkeypatch):
    f = FakeSunshine()
    monkeypatch.setattr(svc_module, 'sunshine_service', f)
    return f


@pytest.fixture
def audit_calls(monkeypatch):
    """audit_helper 가 호출하는 record 를 캡처 (DB 없이)"""
    from util import audit_helper
    calls = []

    def fake_record(category, action, actor_ip, detail=None, **kw):
        calls.append({'category': category, 'action': action, 'detail': detail, 'success': kw.get('success')})
        return True
    monkeypatch.setattr(audit_helper.audit_service, 'record', fake_record)
    return calls


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


def test_status(client, fake):
    resp = client.get('/sunshine/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['stream_state'] == 'BUSY'
    assert data['current_app_name'] == 'Desktop'


def test_list_clients(client, fake):
    resp = client.get('/sunshine/clients')
    assert resp.status_code == 200
    assert resp.get_json()['clients'][0]['uuid'] == 'CA18CAF8-527F-5908-7D91-D9B5D498DC29'


def test_list_clients_api_error_is_502_not_401(client, fake):
    # 401 을 그대로 내리면 프론트가 관리자 API Key 모달을 띄우므로 502 로 구분한다
    fake.fail = SunshineApiError('auth', 401, 'auth_failed')
    resp = client.get('/sunshine/clients')
    assert resp.status_code == 502
    assert resp.get_json()['code'] == 'auth_failed'


def test_submit_pin_success_is_audited_without_pin(client, fake, audit_calls):
    resp = client.post('/sunshine/pin', json={'pin': '1234', 'name': ' SUH-MAC-PC '})
    assert resp.status_code == 200
    assert fake.calls == [('pin', '1234', 'SUH-MAC-PC')]
    assert audit_calls[0]['category'] == AuditCategory.SUNSHINE
    assert audit_calls[0]['action'] == AuditAction.SUNSHINE_PAIR
    assert audit_calls[0]['success'] is True
    assert '1234' not in str(audit_calls[0]['detail'])


@pytest.mark.parametrize('body', [
    {'pin': '12', 'name': 'x'},
    {'pin': 'abcd', 'name': 'x'},
    {'pin': '1234', 'name': ''},
    {'pin': '1234', 'name': 'x' * 65},
])
def test_submit_pin_validation_400_not_audited(client, fake, audit_calls, body):
    resp = client.post('/sunshine/pin', json=body)
    assert resp.status_code == 400
    assert fake.calls == []
    assert audit_calls == []


def test_submit_pin_rejected_by_sunshine(client, fake, audit_calls):
    fake.fail = SunshineApiError('Invalid PIN')
    resp = client.post('/sunshine/pin', json={'pin': '1234', 'name': 'x'})
    assert resp.status_code == 502
    assert audit_calls[0]['success'] is False


def test_unpair_client(client, fake, audit_calls):
    resp = client.post('/sunshine/clients/unpair', json={'uuid': 'CA18CAF8-527F-5908-7D91-D9B5D498DC29', 'name': 'SUH-MAC-PC'})
    assert resp.status_code == 200
    assert fake.calls == [('unpair', 'CA18CAF8-527F-5908-7D91-D9B5D498DC29')]
    assert audit_calls[0]['action'] == AuditAction.SUNSHINE_UNPAIR
    assert audit_calls[0]['detail']['uuid'] == 'CA18CAF8-527F-5908-7D91-D9B5D498DC29'


def test_unpair_client_invalid_uuid(client, fake, audit_calls):
    resp = client.post('/sunshine/clients/unpair', json={'uuid': 'bad uuid!'})
    assert resp.status_code == 400
    assert audit_calls == []


def test_close_session(client, fake, audit_calls):
    resp = client.post('/sunshine/session/close', json={})
    assert resp.status_code == 200
    assert fake.calls == [('close',)]
    assert audit_calls[0]['action'] == AuditAction.SUNSHINE_SESSION_CLOSE


@pytest.mark.parametrize('action,expected', [
    ('start', AuditAction.SUNSHINE_START),
    ('stop', AuditAction.SUNSHINE_STOP),
    ('restart', AuditAction.SUNSHINE_RESTART),
])
def test_control_service(client, fake, audit_calls, action, expected):
    resp = client.post(f'/sunshine/control/{action}', json={})
    assert resp.status_code == 200
    assert fake.calls == [(action,)]
    assert audit_calls[0]['action'] == expected


def test_control_service_failure_is_500_and_audited_failed(client, fake, audit_calls):
    fake.control_ok = False
    resp = client.post('/sunshine/control/restart', json={})
    assert resp.status_code == 500
    assert audit_calls[0]['success'] is False


def test_control_invalid_action(client, fake, audit_calls):
    resp = client.post('/sunshine/control/explode', json={})
    assert resp.status_code == 400
    assert audit_calls == []


def test_logs(client, fake):
    resp = client.get('/sunshine/logs?lines=1')
    assert resp.status_code == 200
    assert resp.get_json()['logs'] == ['b']


def test_logs_bad_lines(client, fake):
    assert client.get('/sunshine/logs?lines=x').status_code == 400
