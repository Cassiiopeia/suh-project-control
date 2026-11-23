"""
gbrain 팀원 API 키 (#221): 발급(암호화 보관), 폐기, 다시 보기, 기존 토큰 연결
원문은 발급·다시 보기 반환값에만 담고 로그·감사·목록에 남기지 않음
브레인 결정은 brain_resolver(brain_id) > (GbrainInstance, 토큰 서비스) 주입 (토큰 카드와 같은 규칙)
"""
import hmac
import logging
import threading
import time

from config import gbrain_member_key_config as config
from service import gbrain_member_repository as repository
from service import secret_cipher as cipher
from service.audit_database_executor import AuditDatabaseUnavailableError
from service.gbrain_instance import PERSONAL_BRAIN_ID, READ_ONLY_SCOPE_PRESET
from service.gbrain_server_service import GbrainServerError

logger = logging.getLogger(__name__)

# gbrain 토큰 이름 최대 길이 (gbrain_token_service.DEVICE_NAME_PATTERN 과 같음)
TOKEN_NAME_MAX_LENGTH = 63
# gbrain 폐기 응답 중 이미 끝난 상태로 보는 코드 2개: 이미 폐기, 목록에 없음
ALREADY_GONE_CODES = ('already_revoked', 'token_not_found')
SECRET_MISSING_MESSAGE = (f'서버에 팀원 키 암호화 비밀 문구({config.ENV_MEMBER_KEY_SECRET})가 없어서 '
                          '발급·다시 보기를 막아 두었어요. 서버 .env 에 추가하고 다시 시작해 주세요')


def run_member_store(action):
    """DB 호출 > 미설정·다운이면 503 (화면은 원인 코드로 구분)"""
    try:
        return action()
    except AuditDatabaseUnavailableError as error:
        logger.warning(f'[gbrain member] rejected 503 : store unavailable {error}')
        raise GbrainServerError('관제소 DB 에 연결하지 못했어요', 'member_store_unavailable', 503)


def to_key_response(key) -> dict:
    """키 행 > 화면 응답 (원문·암호문 없음)"""
    return {
        'id': key.id, 'member_id': key.member_id, 'brain': key.brain_id, 'gbrain_token_id': key.gbrain_token_id,
        'token_name': key.token_name, 'scopes': key.scopes, 'has_stored_secret': key.has_stored_secret,
        'issued_at': key.issued_at.isoformat() if key.issued_at else None,
        'revoked_at': key.revoked_at.isoformat() if key.revoked_at else None, 'is_revoked': key.is_revoked,
    }


def revoke_in_gbrain(token_service, token_id) -> None:
    """gbrain 폐기 (이미 폐기·목록에 없음은 성공으로 봄)"""
    try:
        token_service.revoke_token(token_id)
    except GbrainServerError as error:
        if error.code not in ALREADY_GONE_CODES:
            raise


class RevealAttemptGuard:
    """다시 보기 재확인 실패 잠금: 창(초) 안에 한도만큼 틀리면 창이 지날 때까지 거부 (프로세스 메모리)"""

    def __init__(self, failure_limit=config.REVEAL_FAILURE_LIMIT,
                 window_seconds=config.REVEAL_FAILURE_WINDOW_SECONDS, clock=time.monotonic):
        self.failure_limit = failure_limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._failure_times = []
        self._lock = threading.Lock()

    def check_admin_key(self, entered_admin_key, request_admin_key) -> None:
        """재입력 키 <-> 요청 X-API-Key (nginx 검증 완료 값) 상수 시간 비교"""
        with self._lock:
            now = self.clock()
            self._failure_times = [at for at in self._failure_times if now - at < self.window_seconds]
            if len(self._failure_times) >= self.failure_limit:
                raise GbrainServerError('관리자 키를 여러 번 틀려서 잠시 막아 두었어요. 10분 뒤에 다시 해 주세요',
                                        'reveal_locked', 429)
            is_matched = (isinstance(entered_admin_key, str) and bool(request_admin_key)
                          and hmac.compare_digest(entered_admin_key.encode('utf-8'),
                                                  request_admin_key.encode('utf-8')))
            if not is_matched:
                self._failure_times.append(now)
                raise GbrainServerError('관리자 키가 맞지 않아요', 'admin_key_mismatch', 403)
            self._failure_times.clear()


class GbrainMemberKeyService:
    def __init__(self, brain_resolver, store=repository, reveal_guard=None):
        self.brain_resolver = brain_resolver
        self.store = store
        self.reveal_guard = reveal_guard or RevealAttemptGuard()

    def issue_key(self, member_id, brain_id=None, token_name=None, scope_preset=None) -> dict:
        """비밀 문구 확인 > 활성 팀원 > gbrain 발급 > 암호화 저장 (저장 실패 시 gbrain 폐기) > {key, token, secret, instance}"""
        secret_phrase = self._require_secret_phrase()
        member = self._require_active_member(member_id)
        brain_id = brain_id or PERSONAL_BRAIN_ID
        instance, token_service = self.brain_resolver(brain_id)
        token_name = token_name or self._default_token_name(member.handle, instance.brain_id)
        created = token_service.create_token(token_name, scope_preset or READ_ONLY_SCOPE_PRESET)
        token = created['token']
        try:
            key_id = run_member_store(lambda: self.store.insert_key(
                member.id, instance.brain_id, token['id'], token['name'], token['scopes'],
                cipher.encrypt_secret_text(created['secret'], secret_phrase), cipher.ENCRYPTION_SCHEME))
        except (GbrainServerError, repository.DuplicateKeyError):
            self._compensate_unsaved_token(token_service, token['id'])
            raise GbrainServerError('키를 관제소 DB 에 저장하지 못해서 방금 만든 토큰을 폐기했어요. 다시 발급해 주세요',
                                    'member_key_store_failed', 503)
        logger.info(f'[gbrain member key] issued : member={member.handle} brain={instance.brain_id} id={token["id"]}')
        key = run_member_store(lambda: self.store.find_key(key_id))
        return {'key': to_key_response(key), 'token': token, 'secret': created['secret'], 'instance': instance}

    def revoke_key(self, key_id) -> dict:
        """키 1개: gbrain 폐기 > DB 폐기 시각"""
        key = self._require_key(key_id)
        if key.is_revoked:
            raise GbrainServerError('이미 폐기한 키예요', 'already_revoked', 409)
        _instance, token_service = self.brain_resolver(key.brain_id)
        revoke_in_gbrain(token_service, key.gbrain_token_id)
        run_member_store(lambda: self.store.mark_key_revoked(key.id))
        logger.info(f'[gbrain member key] revoked : key={key.id} brain={key.brain_id} id={key.gbrain_token_id}')
        return to_key_response(run_member_store(lambda: self.store.find_key(key.id)))

    def reveal_key(self, key_id, entered_admin_key, request_admin_key) -> dict:
        """관리자 키 재확인 > 비밀 문구 > 살아 있는 키 > 복호화 > {key, secret, instance}"""
        self.reveal_guard.check_admin_key(entered_admin_key, request_admin_key)
        secret_phrase = self._require_secret_phrase()
        key = self._require_key(key_id)
        if key.is_revoked:
            raise GbrainServerError('폐기한 키는 다시 볼 수 없어요', 'already_revoked', 409)
        stored_secret = run_member_store(lambda: self.store.find_key_secret(key.id))
        if stored_secret is None:
            raise GbrainServerError('이 키는 원문을 보관하지 않았어요 (기존 토큰 연결). 새로 발급해 주세요',
                                    'secret_not_stored', 409)
        try:
            secret = cipher.decrypt_secret_text(stored_secret.encrypted_token, stored_secret.encryption_scheme,
                                                secret_phrase)
        except cipher.SecretCipherError:
            logger.warning(f'[gbrain member key] rejected 500 : decrypt failed key={key.id}')
            raise GbrainServerError('키를 풀지 못했어요. 비밀 문구가 바뀌었다면 이 키를 폐기하고 새로 발급해 주세요',
                                    'decrypt_failed', 500)
        instance, _token_service = self.brain_resolver(key.brain_id)
        logger.info(f'[gbrain member key] revealed : key={key.id} brain={key.brain_id}')
        return {'key': to_key_response(key), 'secret': secret, 'instance': instance}

    def list_unrecorded_tokens(self, brain_id=None) -> list:
        """브레인의 살아 있는 gbrain 토큰 중 관제소 DB 에 없는 것 (원문 없음)"""
        instance, token_service = self.brain_resolver(brain_id or PERSONAL_BRAIN_ID)
        recorded_token_ids = run_member_store(lambda: self.store.list_recorded_token_ids(instance.brain_id))
        return [token for token in token_service.list_tokens()
                if token['is_active'] and token['id'] not in recorded_token_ids]

    def link_token(self, member_id, brain_id, token_id) -> dict:
        """기존 gbrain 토큰 > 팀원에 연결 (원문 없음, 다시 보기 불가)"""
        member = self._require_active_member(member_id)
        instance, token_service = self.brain_resolver(brain_id or PERSONAL_BRAIN_ID)
        token = next((item for item in token_service.list_tokens() if item['id'] == token_id), None)
        if token is None or not token['is_active']:
            raise GbrainServerError('연결할 살아 있는 토큰을 찾지 못했어요', 'token_not_found', 404)
        try:
            key_id = run_member_store(lambda: self.store.insert_key(
                member.id, instance.brain_id, token['id'], token['name'], token['scopes']))
        except repository.DuplicateKeyError:
            raise GbrainServerError('이미 다른 팀원에게 연결한 토큰이에요', 'already_linked', 409)
        logger.info(f'[gbrain member key] linked : member={member.handle} brain={instance.brain_id} id={token_id}')
        return to_key_response(run_member_store(lambda: self.store.find_key(key_id)))

    # ---------- 내부 ----------
    @staticmethod
    def _require_secret_phrase() -> str:
        secret_phrase = config.get_member_key_secret()
        if not secret_phrase:
            raise GbrainServerError(SECRET_MISSING_MESSAGE, 'member_key_secret_missing', 503)
        return secret_phrase

    def _require_active_member(self, member_id):
        member = run_member_store(lambda: self.store.find_member(member_id))
        if member is None:
            raise GbrainServerError('팀원을 찾지 못했어요', 'member_not_found', 404)
        if not member.is_active:
            raise GbrainServerError('종료한 팀원에게는 키를 줄 수 없어요', 'member_ended', 409)
        return member

    def _require_key(self, key_id):
        key = run_member_store(lambda: self.store.find_key(key_id))
        if key is None:
            raise GbrainServerError('키를 찾지 못했어요', 'key_not_found', 404)
        return key

    @staticmethod
    def _default_token_name(handle, brain_id) -> str:
        return f'{handle}-{brain_id}'[:TOKEN_NAME_MAX_LENGTH]

    @staticmethod
    def _compensate_unsaved_token(token_service, token_id) -> None:
        """저장 못 한 토큰 폐기 (실패해도 원래 오류를 돌려줌, 토큰 카드에서 폐기 가능)"""
        try:
            revoke_in_gbrain(token_service, token_id)
            logger.warning(f'[gbrain member key] compensated : revoked unsaved id={token_id}')
        except GbrainServerError as error:
            logger.warning(f'[gbrain member key] compensate failed : id={token_id} code={error.code}')
