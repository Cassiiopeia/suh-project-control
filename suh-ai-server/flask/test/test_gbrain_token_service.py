"""GbrainTokenService: 소유자 로그인·세션 재사용, 목록 요약, 발급 검증, 폐기 확인 (gbrain HTTP 는 가짜)"""
import json
import logging

import pytest
import requests

from config import gbrain_server_config
from service import gbrain_token_service as module
from service.gbrain_server_service import GbrainServerError
from service.gbrain_token_service import GbrainTokenService

ADMIN_TOKEN = 'A' * 43
SESSION_ID = 'f' * 64
MINTED_SECRET = 'gbrain_' + 'x' * 40
ACTIVE_ID = '11111111-2222-3333-4444-555555555555'
REVOKED_ID = '66666666-7777-8888-9999-000000000000'
NEW_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, cookies=None):
        self.status_code = status_code
        self._json_data = json_data
        self.cookies = cookies or {}

    def json(self):
        if self._json_data is None:
            raise ValueError('no json')
        return self._json_data


class FakeGbrain:
    """gbrain 소유자 API 흉내: 로그인 > 세션 쿠키, api-keys 목록·발급·폐기"""

    def __init__(self):
        self.tokens = [
            {'id': ACTIVE_ID, 'name': 'claude-code-mac-public', 'created_at': '2026-11-22T00:00:00Z',
             'last_used_at': '2026-11-22T01:00:00Z', 'status': 'active', 'scopes': ['read', 'write'],
             'token_hash': 'must-not-leak'},
            {'id': REVOKED_ID, 'name': 'old-device', 'created_at': '2026-11-21T00:00:00Z',
             'last_used_at': None, 'status': 'revoked', 'scopes': ['read']},
        ]
        self.login_count = 0
        self.requests = []
        self.is_admin_token_accepted = True
        self.expire_session_once = False
        self.mint_status = 200
        self.mint_body = None
        self.is_revoke_applied = True

    def post(self, url, json=None, timeout=None):
        assert url.endswith('/admin/login')
        if not self.is_admin_token_accepted or json.get('token') != ADMIN_TOKEN:
            return FakeResponse(401, {'error': 'rejected'})
        self.login_count += 1
        return FakeResponse(200, {'status': 'authenticated'}, cookies={'gbrain_admin': SESSION_ID})

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.requests.append((method, url.split('3131')[1], json, headers))
        if self.expire_session_once:
            self.expire_session_once = False
            return FakeResponse(401, {'error': 'Session expired'})
        assert headers == {'Cookie': f'gbrain_admin={SESSION_ID}'}
        if method == 'GET':
            return FakeResponse(200, self.tokens)
        if url.endswith('/api-keys'):
            if self.mint_status != 200:
                return FakeResponse(self.mint_status, {'error': {'message': 'Unknown scope "x".'}})
            return FakeResponse(200, self.mint_body or {'id': NEW_ID, 'name': json['name'], 'token': MINTED_SECRET})
        if url.endswith('/api-keys/revoke'):
            return FakeResponse(200, {'id': json['id'], 'revoked': self.is_revoke_applied})
        raise AssertionError(url)


@pytest.fixture
def fake_gbrain(tmp_path, monkeypatch):
    token_path = tmp_path / 'admin-token'
    token_path.write_text(ADMIN_TOKEN + '\n', encoding='utf-8')
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_ADMIN_TOKEN_FILE', str(token_path))
    fake = FakeGbrain()
    monkeypatch.setattr(module.requests, 'post', fake.post)
    monkeypatch.setattr(module.requests, 'request', fake.request)
    return fake


@pytest.fixture
def service():
    return GbrainTokenService(server_url='http://127.0.0.1:3131')


def test_목록은_사용_중_먼저이고_해시를_담지_않는다(service, fake_gbrain):
    fake_gbrain.tokens.reverse()
    tokens = service.list_tokens()

    assert [token['id'] for token in tokens] == [ACTIVE_ID, REVOKED_ID]
    assert tokens[0]['is_active'] is True and tokens[1]['is_active'] is False
    assert tokens[0]['scopes'] == ['read', 'write']
    assert 'must-not-leak' not in json.dumps(tokens)


def test_소유자_세션은_재사용하고_만료되면_한_번_다시_로그인한다(service, fake_gbrain):
    service.list_tokens()
    service.list_tokens()
    assert fake_gbrain.login_count == 1

    fake_gbrain.expire_session_once = True
    service.list_tokens()
    assert fake_gbrain.login_count == 2


def test_관리자_토큰_파일이_없으면_503(service, fake_gbrain, monkeypatch, tmp_path):
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_ADMIN_TOKEN_FILE', str(tmp_path / 'missing'))
    with pytest.raises(GbrainServerError) as error:
        service.list_tokens()
    assert error.value.code == 'admin_token_missing' and error.value.status_code == 503


def test_관리자_토큰_거부는_502_코드로(service, fake_gbrain):
    fake_gbrain.is_admin_token_accepted = False
    with pytest.raises(GbrainServerError) as error:
        service.list_tokens()
    assert error.value.code == 'admin_token_rejected' and error.value.status_code == 502


def test_gbrain_연결_실패는_unreachable(service, fake_gbrain, monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError('down')
    monkeypatch.setattr(module.requests, 'post', raise_connection_error)
    with pytest.raises(GbrainServerError) as error:
        service.list_tokens()
    assert error.value.code == 'unreachable'


def test_발급은_원문을_한_번_돌려주고_로그에_남기지_않는다(service, fake_gbrain, caplog):
    caplog.set_level(logging.DEBUG)
    created = service.create_token('work-macbook', 'read_only')

    assert created['secret'] == MINTED_SECRET
    assert created['token'] == {'id': NEW_ID, 'name': 'work-macbook', 'scopes': ['read']}
    assert fake_gbrain.requests[-1][2] == {'name': 'work-macbook', 'scopes': ['read']}
    assert MINTED_SECRET not in caplog.text and ADMIN_TOKEN not in caplog.text and SESSION_ID not in caplog.text


@pytest.mark.parametrize('device_name', ['', 'A-upper', '-leading', 'a', 'has space', 'x' * 64, None, 'kor한글'])
def test_발급_기기_이름_검증(service, fake_gbrain, device_name):
    with pytest.raises(GbrainServerError) as error:
        service.create_token(device_name, 'read_write')
    assert error.value.code == 'invalid_name' and error.value.status_code == 400
    assert fake_gbrain.requests == []


def test_발급_권한은_선택지_두_개만(service, fake_gbrain):
    with pytest.raises(GbrainServerError) as error:
        service.create_token('work-macbook', 'admin')
    assert error.value.code == 'invalid_scopes'


def test_사용_중인_같은_이름은_409(service, fake_gbrain):
    with pytest.raises(GbrainServerError) as error:
        service.create_token('claude-code-mac-public', 'read_write')
    assert error.value.code == 'name_in_use' and error.value.status_code == 409
    # 폐기된 이름은 다시 쓸 수 있음
    assert service.create_token('old-device', 'read_write')['token']['name'] == 'old-device'


def test_gbrain_400_은_사유를_그대로(service, fake_gbrain):
    fake_gbrain.mint_status = 400
    with pytest.raises(GbrainServerError) as error:
        service.create_token('work-macbook', 'read_write')
    assert error.value.status_code == 400 and 'Unknown scope' in str(error.value)


def test_형식_밖_발급_응답은_원문을_내보내지_않는다(service, fake_gbrain):
    fake_gbrain.mint_body = {'id': 'not-a-uuid', 'token': MINTED_SECRET}
    with pytest.raises(GbrainServerError) as error:
        service.create_token('work-macbook', 'read_write')
    assert error.value.code == 'invalid_mint_response'
    assert MINTED_SECRET not in str(error.value)


def test_폐기는_id_로_하고_이름과_권한을_돌려준다(service, fake_gbrain):
    revoked = service.revoke_token(ACTIVE_ID)
    assert revoked == {'id': ACTIVE_ID, 'name': 'claude-code-mac-public', 'scopes': ['read', 'write']}
    assert fake_gbrain.requests[-1][1:3] == ('/admin/api/api-keys/revoke', {'id': ACTIVE_ID})


@pytest.mark.parametrize('token_id, code, status_code', [
    ('not-a-uuid', 'invalid_token_id', 400),
    ('99999999-9999-9999-9999-999999999999', 'token_not_found', 404),
    (REVOKED_ID, 'already_revoked', 409),
])
def test_폐기_거부_사유(service, fake_gbrain, token_id, code, status_code):
    with pytest.raises(GbrainServerError) as error:
        service.revoke_token(token_id)
    assert error.value.code == code and error.value.status_code == status_code


def test_gbrain_이_폐기하지_않으면_502(service, fake_gbrain):
    fake_gbrain.is_revoke_applied = False
    with pytest.raises(GbrainServerError) as error:
        service.revoke_token(ACTIVE_ID)
    assert error.value.code == 'revoke_not_applied'
