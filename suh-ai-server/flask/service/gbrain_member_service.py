"""
gbrain 팀원 관리 (#221): 목록, 추가, 수정, 사람별 키 상태(gbrain 실시간), 종료(키 일괄 폐기)
팀원은 관제소에 로그인하지 않음 > 소유자가 기록·발급·전달
"""
import logging
import re

from service import gbrain_member_repository as repository
from service.gbrain_member_key_service import revoke_in_gbrain, run_member_store, to_key_response
from service.gbrain_server_service import GbrainServerError

logger = logging.getLogger(__name__)

# handle: 영문 소문자로 시작, 소문자·숫자·하이픈 2~40자 (gbrain 토큰 이름 앞자리)
HANDLE_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,39}$')
# 입력 최대 길이 (DB 컬럼과 같음)
MAX_LENGTH_BY_FIELD = {'display_name': 100, 'contact': 200, 'memo': 500}
# 사람별 보기 gbrain 상태 3개 외: active / revoked / missing(목록에 없음) / unknown(gbrain 확인 실패)
LIVE_STATUS_MISSING = 'missing'
LIVE_STATUS_UNKNOWN = 'unknown'
LIVE_STATUS_REVOKED = 'revoked'


def to_member_response(member, keys) -> dict:
    """팀원 행 + 그 사람 키 요약 (원문 없음)"""
    return {
        'id': member.id, 'handle': member.handle, 'display_name': member.display_name,
        'contact': member.contact, 'memo': member.memo, 'is_owner': member.is_owner, 'is_active': member.is_active,
        'created_at': member.created_at.isoformat() if member.created_at else None,
        'ended_at': member.ended_at.isoformat() if member.ended_at else None,
        'active_key_count': sum(1 for key in keys if not key.is_revoked),
        'brains': sorted({key.brain_id for key in keys if not key.is_revoked}),
    }


class GbrainMemberService:
    def __init__(self, brain_resolver, store=repository):
        self.brain_resolver = brain_resolver
        self.store = store

    def list_members(self) -> list:
        members = run_member_store(self.store.list_members)
        all_keys = run_member_store(self.store.list_keys)
        return [to_member_response(member, [key for key in all_keys if key.member_id == member.id])
                for member in members]

    def create_member(self, handle, display_name, contact=None, memo=None) -> dict:
        """검증 > 저장 > 응답"""
        if not isinstance(handle, str) or not HANDLE_PATTERN.match(handle):
            raise GbrainServerError('영문 id 는 소문자로 시작하고 소문자·숫자·하이픈으로 2~40자로 써 주세요 (예: kim-dev)',
                                    'invalid_handle', 400)
        fields = self._normalize_fields({'display_name': display_name, 'contact': contact or '', 'memo': memo or ''})
        try:
            member_id = run_member_store(lambda: self.store.insert_member(
                handle, fields['display_name'], fields['contact'], fields['memo']))
        except repository.DuplicateMemberError:
            raise GbrainServerError('같은 영문 id 의 팀원이 이미 있어요', 'handle_in_use', 409)
        logger.info(f'[gbrain member] created : id={member_id} handle={handle}')
        return to_member_response(run_member_store(lambda: self.store.find_member(member_id)), [])

    def update_member(self, member_id, display_name=None, contact=None, memo=None) -> dict:
        """전달된 항목만 수정 (영문 id 는 토큰 이름에 쓰여 바꾸지 않음)"""
        raw_fields = {'display_name': display_name, 'contact': contact, 'memo': memo}
        fields = self._normalize_fields({name: value for name, value in raw_fields.items() if value is not None})
        if not run_member_store(lambda: self.store.update_member(member_id, fields)):
            raise GbrainServerError('팀원을 찾지 못했어요', 'member_not_found', 404)
        member = run_member_store(lambda: self.store.find_member(member_id))
        return to_member_response(member, run_member_store(lambda: self.store.list_keys(member_id)))

    def describe_member_keys(self, member_id) -> list:
        """팀원 키 목록 + 브레인별 gbrain 상태·마지막 사용 (gbrain 이 폐기를 알려 주면 DB 에도 반영)"""
        self._require_member(member_id)
        keys = run_member_store(lambda: self.store.list_keys(member_id))
        live_token_by_id_by_brain = {brain_id: self._read_live_tokens(brain_id)
                                     for brain_id in {key.brain_id for key in keys}}
        described_keys = []
        for key in keys:
            live_token_by_id = live_token_by_id_by_brain[key.brain_id]
            live_token = (live_token_by_id or {}).get(key.gbrain_token_id)
            if live_token and live_token['status'] == LIVE_STATUS_REVOKED and not key.is_revoked:
                run_member_store(lambda: self.store.mark_key_revoked(key.id))
                key = run_member_store(lambda: self.store.find_key(key.id))
            described_keys.append({**to_key_response(key), **self._to_live_fields(live_token_by_id, live_token)})
        return described_keys

    def end_member(self, member_id) -> dict:
        """살아 있는 키 gbrain 일괄 폐기 > 모두 끝나면 팀원 종료 (일부 실패 시 활성 유지·실패 목록)"""
        member = self._require_member(member_id)
        if member.is_owner:
            raise GbrainServerError('소유자는 종료할 수 없어요. 키를 하나씩 폐기해 주세요', 'owner_cannot_end', 409)
        if not member.is_active:
            raise GbrainServerError('이미 종료한 팀원이에요', 'member_ended', 409)
        revoked_key_ids, failures = [], []
        for key in run_member_store(lambda: self.store.list_keys(member_id)):
            if key.is_revoked:
                continue
            try:
                _instance, token_service = self.brain_resolver(key.brain_id)
                revoke_in_gbrain(token_service, key.gbrain_token_id)
            except GbrainServerError as error:
                failures.append({'key_id': key.id, 'brain': key.brain_id, 'code': error.code, 'error': str(error)})
                continue
            run_member_store(lambda: self.store.mark_key_revoked(key.id))
            revoked_key_ids.append(key.id)
        if not failures:
            run_member_store(lambda: self.store.mark_member_ended(member_id))
        logger.info(f'[gbrain member] end : handle={member.handle} revoked={len(revoked_key_ids)} '
                    f'failed={len(failures)}')
        return {'member_id': member_id, 'is_ended': not failures,
                'revoked_key_ids': revoked_key_ids, 'failures': failures}

    # ---------- 내부 ----------
    def _require_member(self, member_id):
        member = run_member_store(lambda: self.store.find_member(member_id))
        if member is None:
            raise GbrainServerError('팀원을 찾지 못했어요', 'member_not_found', 404)
        return member

    def _read_live_tokens(self, brain_id):
        """브레인 gbrain 토큰 목록 > {id: 요약}, 실패 시 None (화면은 확인 불가로 열림)"""
        try:
            _instance, token_service = self.brain_resolver(brain_id)
            return {token['id']: token for token in token_service.list_tokens()}
        except GbrainServerError as error:
            logger.warning(f'[gbrain member] live status skipped : brain={brain_id} code={error.code}')
            return None

    @staticmethod
    def _to_live_fields(live_token_by_id, live_token) -> dict:
        if live_token_by_id is None:
            return {'live_status': LIVE_STATUS_UNKNOWN, 'last_used_at': None}
        if live_token is None:
            return {'live_status': LIVE_STATUS_MISSING, 'last_used_at': None}
        return {'live_status': live_token['status'], 'last_used_at': live_token.get('last_used_at')}

    @staticmethod
    def _normalize_fields(fields: dict) -> dict:
        """앞뒤 공백 제거 + 길이 검사 (이름은 필수)"""
        normalized = {}
        for name, value in fields.items():
            if not isinstance(value, str):
                raise GbrainServerError('입력 형식이 올바르지 않아요', f'invalid_{name}', 400)
            value = value.strip()
            if len(value) > MAX_LENGTH_BY_FIELD[name]:
                raise GbrainServerError(f'{MAX_LENGTH_BY_FIELD[name]}자 이내로 써 주세요', f'invalid_{name}', 400)
            normalized[name] = value
        if 'display_name' in normalized and not normalized['display_name']:
            raise GbrainServerError('이름을 써 주세요', 'invalid_display_name', 400)
        return normalized
