"""GbrainServerService: 상태 조립(비번 미노출), 로그 끝 줄, 관리자 로그인 경로 검증 (HTTP·파일·서비스는 가짜)"""
import json

import pytest
import requests

from config import gbrain_server_config
from service import gbrain_server_service as module
from service.gbrain_server_service import GbrainServerError, GbrainServerService

ADMIN_TOKEN = 'T' * 43
VALID_NONCE = 'ab' * 32
DATABASE_PASSWORD = 'super-secret-password'


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError('no json')
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeWindowsService:
    def __init__(self, state='running'):
        self.state = state

    def get_state(self):
        return self.state


@pytest.fixture
def gbrain_home(tmp_path, monkeypatch):
    """임시 GBRAIN_HOME (config.json 에 비번 포함 DB 주소) + 관리자 토큰 파일"""
    config_dir = tmp_path / '.gbrain'
    config_dir.mkdir()
    (config_dir / 'config.json').write_text(json.dumps({
        'engine': 'postgres',
        'database_url': f'postgresql://gbrain:{DATABASE_PASSWORD}@127.0.0.1:5433/gbrain',
        'embedding_model': 'ollama:qwen3-embedding:0.6b',
        'embedding_dimensions': 1024,
    }), encoding='utf-8')
    token_path = tmp_path / 'admin-token'
    token_path.write_text(ADMIN_TOKEN + '\n', encoding='utf-8')
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_HOME', str(tmp_path))
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_ADMIN_TOKEN_FILE', str(token_path))
    return tmp_path


@pytest.fixture
def service():
    gbrain_service = GbrainServerService(server_url='http://127.0.0.1:3131')
    gbrain_service.windows_service = FakeWindowsService()
    return gbrain_service


def test_상태는_서비스_헬스_구성을_합치고_비번은_담지_않는다(service, gbrain_home, monkeypatch):
    health = {'status': 'ok', 'version': '0.60.739.0',
              'build': {'installed_version': '0.60.739.0', 'restart_pending': False}}
    monkeypatch.setattr(module.requests, 'get', lambda url, timeout: FakeResponse(200, health))

    status = service.get_status()

    assert status['service_running'] is True and status['is_healthy'] is True
    assert status['version'] == '0.60.739.0' and status['is_restart_pending'] is False
    assert status['database'] == {'host': '127.0.0.1', 'port': 5433, 'name': 'gbrain', 'user': 'gbrain'}
    assert status['embedding_model'] == 'ollama:qwen3-embedding:0.6b'
    assert status['has_admin_token'] is True
    assert DATABASE_PASSWORD not in json.dumps(status)


def test_헬스가_없어도_상태는_응답한다(service, gbrain_home, monkeypatch):
    service.windows_service = FakeWindowsService('stopped')

    def refuse(url, timeout):
        raise requests.ConnectionError('refused')
    monkeypatch.setattr(module.requests, 'get', refuse)

    status = service.get_status()

    assert status['service_running'] is False and status['is_healthy'] is False
    assert status['version'] is None


def test_설정_파일을_못_읽으면_config_error(service, tmp_path, monkeypatch):
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_HOME', str(tmp_path / 'missing'))
    assert service.read_config_summary() == {'config_error': 'config_unreadable'}


def test_로그는_끝에서_요청한_줄만_최대_500줄(service, tmp_path):
    log_path = tmp_path / 'gbrain-http.log'
    log_path.write_text('\n'.join(f'line {index}' for index in range(800)), encoding='utf-8')
    service.log_path = str(log_path)

    assert service.read_logs(3) == ['line 797', 'line 798', 'line 799']
    assert len(service.read_logs(9999)) == 500


def test_로그_파일이_없으면_log_unreadable(service, tmp_path):
    service.log_path = str(tmp_path / 'none.log')
    with pytest.raises(GbrainServerError) as error_info:
        service.read_logs(10)
    assert error_info.value.code == 'log_unreadable' and error_info.value.status_code == 404


def test_관리자_로그인은_토큰으로_발급하고_경로만_돌려준다(service, gbrain_home, monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, headers))
        return FakeResponse(200, {'url': f'http://localhost:3131/admin/auth/{VALID_NONCE}', 'expires_in': 300})
    monkeypatch.setattr(module.requests, 'post', fake_post)
    # 발급한 링크를 GET 하면 안 됨
    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: pytest.fail('login link fetched'))

    admin_login = service.create_admin_login()

    assert admin_login['login_path'] == f'/admin/auth/{VALID_NONCE}'
    assert calls[0][0] == 'http://127.0.0.1:3131/admin/api/issue-magic-link'
    assert calls[0][1] == {'Authorization': f'Bearer {ADMIN_TOKEN}'}
    assert service.is_admin_gate_valid(admin_login['gate_cookie_value']) is True


def test_관리자_토큰_파일이_없으면_503(service, tmp_path, monkeypatch):
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_ADMIN_TOKEN_FILE', str(tmp_path / 'none'))
    with pytest.raises(GbrainServerError) as error_info:
        service.create_admin_login()
    assert error_info.value.code == 'admin_token_missing' and error_info.value.status_code == 503


@pytest.mark.parametrize('link_url', [
    'http://evil.example/redirect',
    'http://localhost:3131/admin/auth/short',
    f'http://localhost:3131/admin/auth/{VALID_NONCE}/../../mcp',
    '',
])
def test_형식_밖_링크는_거부한다(service, gbrain_home, monkeypatch, link_url):
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs: FakeResponse(200, {'url': link_url}))
    with pytest.raises(GbrainServerError) as error_info:
        service.create_admin_login()
    assert error_info.value.code == 'invalid_login_link'


def test_gbrain_이_토큰을_거부하면_admin_token_rejected(service, gbrain_home, monkeypatch):
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs: FakeResponse(401, {}))
    with pytest.raises(GbrainServerError) as error_info:
        service.create_admin_login()
    assert error_info.value.code == 'admin_token_rejected' and error_info.value.status_code == 502


def test_gbrain_연결_실패면_unreachable(service, gbrain_home, monkeypatch):
    def refuse(*args, **kwargs):
        raise requests.ConnectionError('refused')
    monkeypatch.setattr(module.requests, 'post', refuse)
    with pytest.raises(GbrainServerError) as error_info:
        service.create_admin_login()
    assert error_info.value.code == 'unreachable'
