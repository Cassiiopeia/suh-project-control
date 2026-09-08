"""sunshine_service 단위 테스트 — HTTP/PowerShell 은 전부 모킹"""
import subprocess

import pytest
import requests

from service import sunshine_service as mod
from service.sunshine_service import SunshineApiError, SunshineService

SERVERINFO_BUSY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<root status_code="200"><hostname>SUH-PROJECT-AI</hostname><appversion>7.1.431.-1</appversion>'
    '<currentgame>881448767</currentgame><state>SUNSHINE_SERVER_BUSY</state></root>'
)
SERVERINFO_FREE = (
    '<root status_code="200"><hostname>SUH-PROJECT-AI</hostname><appversion>7.1.431.-1</appversion>'
    '<currentgame>0</currentgame><state>SUNSHINE_SERVER_FREE</state></root>'
)


class FakeResp:
    def __init__(self, status=200, json_data=None, text=''):
        self.status_code = status
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError('no json')
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv('SUNSHINE_WEB_USER', 'kimchi')
    monkeypatch.setenv('SUNSHINE_WEB_PASSWORD', 'secret')


@pytest.fixture
def svc():
    return SunshineService(api_url='https://127.0.0.1:47990', serverinfo_url='http://127.0.0.1:47989/serverinfo',
                           service_name='SunshineService')


# ---------- serverinfo ----------
def test_parse_serverinfo_busy():
    info = SunshineService.parse_serverinfo(SERVERINFO_BUSY)
    assert info == {'host_name': 'SUH-PROJECT-AI', 'version': '7.1.431.-1',
                    'stream_state': 'BUSY', 'current_app_id': '881448767'}


def test_parse_serverinfo_free_has_no_app():
    info = SunshineService.parse_serverinfo(SERVERINFO_FREE)
    assert info['stream_state'] == 'FREE'
    assert info['current_app_id'] is None


def test_fetch_serverinfo_returns_none_when_down(svc, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError('refused')
    monkeypatch.setattr(mod.requests, 'get', boom)
    assert svc.fetch_serverinfo() is None


def test_resolve_app_name_known_and_unknown():
    assert SunshineService.resolve_app_name('881448767') == 'Desktop'
    assert SunshineService.resolve_app_name('123') is None
    assert SunshineService.resolve_app_name(None) is None


# ---------- 웹 API ----------
def test_request_without_credentials_raises(svc, monkeypatch):
    monkeypatch.delenv('SUNSHINE_WEB_USER', raising=False)
    monkeypatch.delenv('SUNSHINE_WEB_PASSWORD', raising=False)
    with pytest.raises(SunshineApiError) as ei:
        svc.list_clients()
    assert ei.value.code == 'credentials_missing'


def test_list_clients_uses_basic_auth_and_maps_fields(svc, creds, monkeypatch):
    captured = {}

    def fake_request(method, url, **kw):
        captured.update(method=method, url=url, **kw)
        return FakeResp(200, {'named_certs': [{'name': 'SUH-MAC-PC', 'uuid': 'AAA-1'}], 'status': True})
    monkeypatch.setattr(mod.requests, 'request', fake_request)

    clients = svc.list_clients()
    assert clients == [{'name': 'SUH-MAC-PC', 'uuid': 'AAA-1'}]
    assert captured['method'] == 'GET'
    assert captured['url'] == 'https://127.0.0.1:47990/api/clients/list'
    assert captured['verify'] is False
    assert captured['auth'].username == 'kimchi'


def test_submit_pin_posts_pin_and_name(svc, creds, monkeypatch):
    captured = {}

    def fake_request(method, url, **kw):
        captured.update(method=method, url=url, body=kw.get('json'))
        return FakeResp(200, {'status': True})
    monkeypatch.setattr(mod.requests, 'request', fake_request)

    svc.submit_pin('1234', 'SUH-MAC-PC')
    assert captured == {'method': 'POST', 'url': 'https://127.0.0.1:47990/api/pin',
                        'body': {'pin': '1234', 'name': 'SUH-MAC-PC'}}


def test_status_false_body_raises(svc, creds, monkeypatch):
    monkeypatch.setattr(mod.requests, 'request',
                        lambda *a, **k: FakeResp(200, {'status': False, 'error': 'Invalid PIN'}))
    with pytest.raises(SunshineApiError, match='Invalid PIN'):
        svc.submit_pin('0000', 'x')


def test_http_401_maps_to_auth_failed(svc, creds, monkeypatch):
    monkeypatch.setattr(mod.requests, 'request', lambda *a, **k: FakeResp(401, {'status': False}))
    with pytest.raises(SunshineApiError) as ei:
        svc.close_session()
    assert ei.value.code == 'auth_failed'


def test_connection_error_maps_to_unreachable(svc, creds, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError('refused')
    monkeypatch.setattr(mod.requests, 'request', boom)
    with pytest.raises(SunshineApiError) as ei:
        svc.unpair_client('AAA')
    assert ei.value.code == 'unreachable'


def test_read_logs_tails_plain_text(svc, creds, monkeypatch):
    text = '\n'.join(f'line{i}' for i in range(10))
    monkeypatch.setattr(mod.requests, 'request', lambda *a, **k: FakeResp(200, None, text=text))
    assert svc.read_logs(3) == ['line7', 'line8', 'line9']


# ---------- Windows 서비스 ----------
def test_is_service_running_parses_powershell(svc, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='Running\n', stderr='')
    monkeypatch.setattr(mod.subprocess, 'run', fake_run)

    assert svc.is_service_running() is True
    assert "Get-Service -Name 'SunshineService'" in calls[0][-1]


def test_is_service_running_false_when_powershell_missing(svc, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError('powershell')
    monkeypatch.setattr(mod.subprocess, 'run', boom)
    assert svc.is_service_running() is False


def test_restart_service_uses_restart_verb(svc, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
    monkeypatch.setattr(mod.subprocess, 'run', fake_run)

    assert svc.restart_service() is True
    assert "Restart-Service -Name 'SunshineService'" in calls[0][-1]


def test_stop_service_false_on_nonzero_exit(svc, monkeypatch):
    monkeypatch.setattr(mod.subprocess, 'run',
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='', stderr='denied'))
    assert svc.stop_service() is False


# ---------- 종합 상태 ----------
def test_get_status_combines_sources(svc, creds, monkeypatch):
    monkeypatch.setattr(svc, 'fetch_serverinfo', lambda: SunshineService.parse_serverinfo(SERVERINFO_BUSY))
    monkeypatch.setattr(svc, 'is_service_running', lambda: True)
    status = svc.get_status()
    assert status['service_running'] is True
    assert status['api_reachable'] is True
    assert status['credentials_configured'] is True
    assert status['stream_state'] == 'BUSY'
    assert status['current_app_name'] == 'Desktop'
    assert status['public_host'] == 'suh-project.synology.me'


def test_get_status_when_sunshine_down(svc, monkeypatch):
    monkeypatch.delenv('SUNSHINE_WEB_USER', raising=False)
    monkeypatch.setattr(svc, 'fetch_serverinfo', lambda: None)
    monkeypatch.setattr(svc, 'is_service_running', lambda: False)
    status = svc.get_status()
    assert status['api_reachable'] is False
    assert status['stream_state'] == 'UNKNOWN'
    assert status['credentials_configured'] is False
    assert status['current_app_id'] is None
