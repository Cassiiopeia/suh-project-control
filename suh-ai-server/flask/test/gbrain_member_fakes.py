"""gbrain 팀원 키 테스트 공통 가짜 (#221): 메모리 저장소(DB 대신), gbrain 토큰 서비스, 브레인 결정기"""
import itertools
import uuid
from datetime import datetime, timezone

from service import gbrain_member_repository as repository
from service.audit_database_executor import AuditDatabaseUnavailableError
from service.gbrain_instance import build_personal_instance, build_team_instance
from service.gbrain_member_repository import GbrainMember, GbrainMemberApiKey, StoredKeySecret
from service.gbrain_server_service import GbrainServerError

TEAM_BRAIN_ID = 'passql'


def make_secret() -> str:
    return 'gbrain_' + uuid.uuid4().hex + uuid.uuid4().hex


class FakeTokenService:
    """gbrain 소유자 API 대신: 발급(새 id·원문), 목록(원문 없음), 폐기"""

    def __init__(self):
        self.tokens = {}
        self.issued_secrets = []
        self.create_error = None
        self.list_error = None
        self.revoke_error_by_id = {}

    def create_token(self, device_name, scope_preset):
        if self.create_error:
            raise self.create_error
        token_id = str(uuid.uuid4())
        scopes = ['read'] if scope_preset == 'read_only' else ['read', 'write']
        secret = make_secret()
        self.issued_secrets.append(secret)
        self.tokens[token_id] = {'id': token_id, 'name': device_name, 'scopes': scopes, 'status': 'active',
                                 'is_active': True, 'created_at': None, 'last_used_at': '2026-11-23T01:00:00Z'}
        return {'token': {'id': token_id, 'name': device_name, 'scopes': scopes}, 'secret': secret}

    def add_existing_token(self, name, status='active') -> str:
        token_id = str(uuid.uuid4())
        self.tokens[token_id] = {'id': token_id, 'name': name, 'scopes': ['read', 'write'], 'status': status,
                                 'is_active': status == 'active', 'created_at': None, 'last_used_at': None}
        return token_id

    def list_tokens(self):
        if self.list_error:
            raise self.list_error
        return [dict(token) for token in self.tokens.values()]

    def revoke_token(self, token_id):
        if token_id in self.revoke_error_by_id:
            raise self.revoke_error_by_id[token_id]
        token = self.tokens.get(token_id)
        if token is None:
            raise GbrainServerError('토큰을 찾지 못했어요', 'token_not_found', 404)
        if not token['is_active']:
            raise GbrainServerError('이미 폐기한 토큰이에요', 'already_revoked', 409)
        token.update(status='revoked', is_active=False)
        return {'id': token_id, 'name': token['name'], 'scopes': token['scopes']}


class FakeBrainResolver:
    """브레인 id > (GbrainInstance, 가짜 토큰 서비스): 개인 + 팀 1개"""

    def __init__(self):
        self.token_service_by_brain = {'personal': FakeTokenService(), TEAM_BRAIN_ID: FakeTokenService()}
        self.instance_by_brain = {'personal': build_personal_instance(),
                                  TEAM_BRAIN_ID: build_team_instance(TEAM_BRAIN_ID, 8101, 'gbrain_passql', 'passql_writer')}

    def __call__(self, brain_id):
        brain_id = brain_id or 'personal'
        if brain_id not in self.instance_by_brain:
            raise GbrainServerError('팀 브레인을 찾지 못했어요', 'team_brain_not_found', 404)
        return self.instance_by_brain[brain_id], self.token_service_by_brain[brain_id]


class FakeMemberStore:
    """gbrain_member_repository 와 같은 함수 모양의 메모리 저장소 (소유자 1명으로 시작)"""

    def __init__(self):
        self.members = {}
        self.keys = {}
        self.secret_by_key_id = {}
        self.ids = itertools.count(1)
        self.is_unavailable = False
        self.fail_insert_key = False
        self.insert_member('owner', '소유자', '', '')
        self.members[1].is_owner = True

    def _check(self):
        if self.is_unavailable:
            raise AuditDatabaseUnavailableError('database url not set')

    def list_members(self):
        self._check()
        return list(self.members.values())

    def find_member(self, member_id):
        self._check()
        return self.members.get(member_id)

    def insert_member(self, handle, display_name, contact, memo):
        self._check()
        if any(member.handle == handle for member in self.members.values()):
            raise repository.DuplicateMemberError(handle)
        member_id = next(self.ids)
        now = datetime.now(timezone.utc)
        self.members[member_id] = GbrainMember(member_id, handle, display_name, contact, memo, False, True, now, now, None)
        return member_id

    def update_member(self, member_id, fields):
        self._check()
        member = self.members.get(member_id)
        if member is None:
            return False
        for name, value in fields.items():
            setattr(member, name, value)
        return True

    def mark_member_ended(self, member_id):
        member = self.members[member_id]
        member.is_active = False
        member.ended_at = datetime.now(timezone.utc)

    def list_keys(self, member_id=None):
        self._check()
        return [key for key in self.keys.values() if member_id is None or key.member_id == member_id]

    def find_key(self, key_id):
        self._check()
        return self.keys.get(key_id)

    def find_key_secret(self, key_id):
        return self.secret_by_key_id.get(key_id)

    def list_recorded_token_ids(self, brain_id):
        return {key.gbrain_token_id for key in self.keys.values() if key.brain_id == brain_id}

    def insert_key(self, member_id, brain_id, gbrain_token_id, token_name, scopes,
                   encrypted_token=None, encryption_scheme=None):
        if self.fail_insert_key:
            raise AuditDatabaseUnavailableError('query failed: OperationalError')
        if gbrain_token_id in self.list_recorded_token_ids(brain_id):
            raise repository.DuplicateKeyError(gbrain_token_id)
        key_id = next(self.ids)
        self.keys[key_id] = GbrainMemberApiKey(key_id, member_id, brain_id, gbrain_token_id, token_name, list(scopes),
                                               encrypted_token is not None, datetime.now(timezone.utc), None)
        if encrypted_token is not None:
            self.secret_by_key_id[key_id] = StoredKeySecret(encrypted_token, encryption_scheme)
        return key_id

    def mark_key_revoked(self, key_id):
        key = self.keys[key_id]
        if key.revoked_at is None:
            key.revoked_at = datetime.now(timezone.utc)
