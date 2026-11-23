"""
gbrain MCP 기기 토큰 관리: 목록, 발급, 폐기 (#207), 브레인(개인·팀)마다 서비스 1개 (#210)
gbrain 소유자 API 경유: 관리자 토큰 > POST /admin/login > 세션 쿠키 > /admin/api/api-keys (CLI 실행 없음)
토큰 원문은 발급 응답에만 담아 돌려주고 기록·저장하지 않음
"""
import logging
import re
import threading
import time

import requests

from config.gbrain_server_config import (
    GBRAIN_HTTP_TIMEOUT_SECONDS, GBRAIN_OWNER_SESSION_REUSE_SECONDS, GBRAIN_SERVER_URL, read_admin_token,
)
from service.gbrain_instance import READ_ONLY_SCOPE_PRESET, READ_WRITE_SCOPE_PRESET
from service.gbrain_server_service import ADMIN_TOKEN_MISSING_MESSAGE, GbrainServerError

logger = logging.getLogger(__name__)

# 기기 이름: 소문자·숫자로 시작, 소문자·숫자·하이픈, 2~63자
DEVICE_NAME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,62}$')
# gbrain 토큰 id (access_tokens.id UUID)
TOKEN_ID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
# gbrain 발급 토큰 원문 접두사 (형식 밖 응답은 화면에 내보내지 않음)
TOKEN_SECRET_PREFIX = 'gbrain_'

# 권한 선택지 2개 > gbrain 권한 목록
SCOPES_BY_PRESET = {
    READ_WRITE_SCOPE_PRESET: ['read', 'write'],
    READ_ONLY_SCOPE_PRESET: ['read'],
}

OWNER_LOGIN_PATH = '/admin/login'
OWNER_SESSION_COOKIE_NAME = 'gbrain_admin'
API_KEYS_PATH = '/admin/api/api-keys'
API_KEYS_REVOKE_PATH = '/admin/api/api-keys/revoke'
# gbrain 거부 사유를 화면에 옮길 때 최대 길이
GBRAIN_MESSAGE_MAX_LENGTH = 200


class GbrainTokenService:
    def __init__(self, server_url=GBRAIN_SERVER_URL, timeout_seconds=GBRAIN_HTTP_TIMEOUT_SECONDS,
                 admin_token_file=None):
        self.server_url = server_url.rstrip('/')
        self.timeout_seconds = timeout_seconds
        # None: 개인 브레인 관리자 토큰 (팀 브레인은 자기 토큰 파일, #210)
        self.admin_token_file = admin_token_file
        # 소유자 세션 캐시 (메모리만): 요청마다 로그인하면 gbrain 세션이 계속 쌓임
        self._owner_session_id = None
        self._owner_session_expires_at = 0.0
        self._owner_session_lock = threading.Lock()

    # ---------- 공개 동작 ----------
    def list_tokens(self) -> list:
        """토큰 목록 (원문 없음): 사용 중 먼저, 같은 상태는 최근 발급 순"""
        response = self._request_admin_api('GET', API_KEYS_PATH)
        if response.status_code >= 400:
            raise self._gbrain_failure('[gbrain token list]', response, 'gbrain 토큰 목록을 불러오지 못했어요')
        try:
            raw_tokens = response.json()
        except ValueError:
            raw_tokens = None
        if not isinstance(raw_tokens, list):
            logger.warning('[gbrain token list] rejected 502 : unexpected list shape')
            raise GbrainServerError('gbrain 토큰 목록 형식이 예상과 달라요', 'invalid_token_list')
        tokens = [self.to_token_summary(raw_token) for raw_token in raw_tokens if isinstance(raw_token, dict)]
        # 안정 정렬: gbrain 의 최근 발급 순을 유지한 채 사용 중을 앞으로
        return sorted(tokens, key=lambda token: not token['is_active'])

    def create_token(self, device_name, scope_preset) -> dict:
        """기기 토큰 발급: 검증 > 같은 이름 사용 중 확인 > gbrain 발급 > {token 요약, secret 원문}"""
        scopes = self._validate_create_request(device_name, scope_preset)
        if any(token['name'] == device_name and token['is_active'] for token in self.list_tokens()):
            raise GbrainServerError('같은 이름의 토큰이 이미 있어요. 다른 기기 이름을 써 주세요',
                                    'name_in_use', 409)

        response = self._request_admin_api('POST', API_KEYS_PATH, {'name': device_name, 'scopes': scopes})
        if response.status_code >= 400:
            raise self._gbrain_failure('[gbrain token create]', response, 'gbrain 토큰을 발급하지 못했어요')
        minted = self._read_minted_token(response)
        logger.info(f'[gbrain token create] created : name={device_name} id={minted["id"]} scopes={",".join(scopes)}')
        return {
            'token': {'id': minted['id'], 'name': device_name, 'scopes': scopes},
            'secret': minted['secret'],
        }

    def revoke_token(self, token_id) -> dict:
        """토큰 1개 폐기 (id 기준, 이름은 겹칠 수 있음): 확인 > gbrain 폐기 > {id, name, scopes}"""
        if not isinstance(token_id, str) or not TOKEN_ID_PATTERN.match(token_id):
            raise GbrainServerError('토큰 id 형식이 올바르지 않아요', 'invalid_token_id', 400)
        target_token = next((token for token in self.list_tokens() if token['id'] == token_id), None)
        if target_token is None:
            raise GbrainServerError('토큰을 찾지 못했어요', 'token_not_found', 404)
        if not target_token['is_active']:
            raise GbrainServerError('이미 폐기한 토큰이에요', 'already_revoked', 409)

        response = self._request_admin_api('POST', API_KEYS_REVOKE_PATH, {'id': token_id})
        if response.status_code >= 400:
            raise self._gbrain_failure('[gbrain token revoke]', response, 'gbrain 토큰을 폐기하지 못했어요')
        try:
            is_revoked = bool(response.json().get('revoked'))
        except (ValueError, AttributeError):
            is_revoked = False
        if not is_revoked:
            logger.warning(f'[gbrain token revoke] rejected 502 : gbrain did not revoke id={token_id}')
            raise GbrainServerError('gbrain 이 토큰을 폐기하지 않았어요. 목록을 새로고침해 확인해 주세요',
                                    'revoke_not_applied')
        logger.info(f'[gbrain token revoke] revoked : name={target_token["name"]} id={token_id}')
        return {'id': token_id, 'name': target_token['name'], 'scopes': target_token['scopes']}

    @staticmethod
    def to_token_summary(raw_token: dict) -> dict:
        """gbrain 토큰 행 > 화면 요약 (원문·해시 없음, 필요한 필드만)"""
        scopes = raw_token.get('scopes')
        status = raw_token.get('status')
        return {
            'id': str(raw_token.get('id', '')),
            'name': str(raw_token.get('name', '')),
            'scopes': [str(scope) for scope in scopes] if isinstance(scopes, list) else [],
            'created_at': raw_token.get('created_at'),
            'last_used_at': raw_token.get('last_used_at'),
            'status': status,
            'is_active': status == 'active',
        }

    # ---------- 검증 ----------
    @staticmethod
    def _validate_create_request(device_name, scope_preset) -> list:
        if not isinstance(device_name, str) or not DEVICE_NAME_PATTERN.match(device_name):
            raise GbrainServerError('기기 이름은 영어 소문자·숫자·하이픈으로 2~63자로 써 주세요 (예: work-macbook)',
                                    'invalid_name', 400)
        scopes = SCOPES_BY_PRESET.get(scope_preset)
        if scopes is None:
            raise GbrainServerError('권한은 읽기+쓰기 또는 읽기 전용 중에서 골라 주세요', 'invalid_scopes', 400)
        return list(scopes)

    @staticmethod
    def _read_minted_token(response) -> dict:
        """발급 응답 > {id, secret} (형식 밖이면 원문을 내보내지 않고 502)"""
        try:
            minted = response.json()
            token_id = str(minted.get('id', ''))
            secret = minted.get('token')
        except (ValueError, AttributeError):
            token_id, secret = '', None
        is_secret_valid = isinstance(secret, str) and secret.startswith(TOKEN_SECRET_PREFIX) and not re.search(r'\s', secret)
        if not TOKEN_ID_PATTERN.match(token_id) or not is_secret_valid:
            logger.warning('[gbrain token create] rejected 502 : unexpected mint response shape')
            raise GbrainServerError('gbrain 발급 응답 형식이 예상과 달라요. 목록을 확인하고 필요하면 폐기해 주세요',
                                    'invalid_mint_response')
        return {'id': token_id, 'secret': secret}

    # ---------- gbrain 소유자 API 호출 ----------
    def _request_admin_api(self, method, path, json_body=None):
        """소유자 세션으로 호출, 세션 만료(401)면 1회 다시 로그인 후 재시도"""
        for attempt_number in (1, 2):
            session_id = self._get_owner_session_id(is_forced_login=attempt_number == 2)
            try:
                response = requests.request(method, self.server_url + path, json=json_body,
                                            headers={'Cookie': f'{OWNER_SESSION_COOKIE_NAME}={session_id}'},
                                            timeout=self.timeout_seconds)
            except requests.RequestException as error:
                logger.warning(f'[gbrain token] rejected 502 : server unreachable {type(error).__name__}')
                raise GbrainServerError('gbrain 서버에 연결할 수 없어요', 'unreachable')
            if response.status_code != 401:
                return response
        logger.warning('[gbrain token] rejected 502 : owner session not accepted after re-login')
        raise GbrainServerError('gbrain 이 관리자 세션을 거부했어요', 'owner_session_rejected')

    def _get_owner_session_id(self, is_forced_login=False) -> str:
        with self._owner_session_lock:
            is_session_reusable = self._owner_session_id and time.monotonic() < self._owner_session_expires_at
            if is_session_reusable and not is_forced_login:
                return self._owner_session_id
            self._owner_session_id = self._login_owner()
            self._owner_session_expires_at = time.monotonic() + GBRAIN_OWNER_SESSION_REUSE_SECONDS
            return self._owner_session_id

    def _login_owner(self) -> str:
        """관리자 토큰 > gbrain 소유자 세션 id (토큰·세션 값은 기록하지 않음)"""
        admin_token = read_admin_token(self.admin_token_file)
        if admin_token is None:
            raise GbrainServerError(ADMIN_TOKEN_MISSING_MESSAGE, 'admin_token_missing', 503)
        try:
            response = requests.post(self.server_url + OWNER_LOGIN_PATH, json={'token': admin_token},
                                     timeout=self.timeout_seconds)
        except requests.RequestException as error:
            logger.warning(f'[gbrain token] rejected 502 : server unreachable {type(error).__name__}')
            raise GbrainServerError('gbrain 서버에 연결할 수 없어요', 'unreachable')
        if response.status_code == 401:
            logger.warning('[gbrain token] rejected 502 : admin token not accepted by gbrain')
            raise GbrainServerError('gbrain 이 관리자 토큰을 거부했어요 (서비스 재시작이 필요할 수 있어요)',
                                    'admin_token_rejected')
        # Secure 쿠키라 http 내부 호출에선 쿠키 저장소가 다시 보내지 않음 > 값만 꺼내 직접 헤더로 보냄
        session_id = response.cookies.get(OWNER_SESSION_COOKIE_NAME)
        if response.status_code >= 400 or not session_id:
            logger.warning(f'[gbrain token] rejected 502 : owner login failed status {response.status_code}')
            raise GbrainServerError('gbrain 관리자 로그인에 실패했어요', 'owner_login_failed')
        return session_id

    @staticmethod
    def _gbrain_failure(log_prefix, response, fallback_message) -> GbrainServerError:
        """gbrain 오류 응답 > 400 은 사유 그대로(입력 문제), 그 외 502"""
        gbrain_message = GbrainTokenService._read_gbrain_message(response)
        logger.warning(f'{log_prefix} rejected {response.status_code} : gbrain status {response.status_code}')
        if response.status_code == 400:
            return GbrainServerError(gbrain_message or fallback_message, 'gbrain_rejected', 400)
        return GbrainServerError(f'{fallback_message} (gbrain HTTP {response.status_code})', 'gbrain_error')

    @staticmethod
    def _read_gbrain_message(response) -> str:
        """gbrain 오류 본문에서 사람용 문구만 (모양: {message} / {error: {message}} / {error: '...'})"""
        try:
            body = response.json()
        except ValueError:
            return ''
        if not isinstance(body, dict):
            return ''
        error_part = body.get('error')
        candidates = [body.get('message'), error_part.get('message') if isinstance(error_part, dict) else error_part]
        message = next((candidate for candidate in candidates if isinstance(candidate, str) and candidate), '')
        return message[:GBRAIN_MESSAGE_MAX_LENGTH]


gbrain_token_service = GbrainTokenService()

# 팀 브레인 토큰 서비스 캐시: 브레인마다 소유자 세션을 따로 재사용
_team_token_services = {}
_team_token_services_lock = threading.Lock()


def get_token_service_for(instance) -> GbrainTokenService:
    """GbrainInstance > 그 브레인 토큰 서비스 (개인은 모듈 단일 객체, 팀은 브레인별 캐시)"""
    if not instance.is_team:
        return gbrain_token_service
    cache_key = (instance.brain_id, instance.port, instance.admin_token_file)
    with _team_token_services_lock:
        if cache_key not in _team_token_services:
            _team_token_services[cache_key] = GbrainTokenService(server_url=instance.server_url,
                                                                 admin_token_file=instance.admin_token_file)
        return _team_token_services[cache_key]
