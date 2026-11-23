"""
gbrain_member / gbrain_member_api_key 표 접근 (#221): 팀원 목록·추가·수정·종료, 키 목록·추가·폐기 표시
암호문(encrypted_token)은 find_key_secret 에서만 읽음 (목록 조회는 암호문을 꺼내지 않음)
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psycopg2

from service.audit_database_executor import execute_audit_sql

MEMBER_COLUMNS = ('id, handle, display_name, contact, memo, is_owner, is_active, '
                  'created_at, updated_at, ended_at')
# 암호문 제외, 저장 여부만 boolean 으로
KEY_COLUMNS = ('id, member_id, brain_id, gbrain_token_id, token_name, scopes, '
               '(encrypted_token IS NOT NULL) AS has_stored_secret, issued_at, revoked_at')
# 수정 허용 컬럼 (SQL 조립 시 이 목록 밖 키는 무시)
UPDATABLE_MEMBER_COLUMNS = ('display_name', 'contact', 'memo')
SCOPE_DELIMITER = ','


class DuplicateMemberError(Exception):
    """같은 handle 이미 등록"""


class DuplicateKeyError(Exception):
    """같은 브레인의 같은 gbrain 토큰 이미 기록"""


@dataclass
class GbrainMember:
    id: int
    handle: str
    display_name: str
    contact: str
    memo: str
    is_owner: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    ended_at: Optional[datetime]


@dataclass
class GbrainMemberApiKey:
    id: int
    member_id: int
    brain_id: str
    gbrain_token_id: str
    token_name: str
    scopes: list
    has_stored_secret: bool
    issued_at: datetime
    revoked_at: Optional[datetime]

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


@dataclass
class StoredKeySecret:
    """다시 보기용 암호문 (메모리 전용)"""
    encrypted_token: bytes
    encryption_scheme: str


# ---------- 팀원 ----------
def list_members() -> list:
    rows = execute_audit_sql(f'SELECT {MEMBER_COLUMNS} FROM gbrain_member ORDER BY is_owner DESC, is_active DESC, id',
                             fetch='all')
    return [GbrainMember(*row) for row in rows]


def find_member(member_id: int):
    row = execute_audit_sql(f'SELECT {MEMBER_COLUMNS} FROM gbrain_member WHERE id = %s', (member_id,), fetch='one')
    return GbrainMember(*row) if row else None


def find_owner_member():
    row = execute_audit_sql(f'SELECT {MEMBER_COLUMNS} FROM gbrain_member WHERE is_owner ORDER BY id LIMIT 1',
                            fetch='one')
    return GbrainMember(*row) if row else None


def insert_member(handle, display_name, contact, memo) -> int:
    try:
        row = execute_audit_sql(
            'INSERT INTO gbrain_member (handle, display_name, contact, memo) VALUES (%s, %s, %s, %s) RETURNING id',
            (handle, display_name, contact, memo), fetch='one')
    except psycopg2.errors.UniqueViolation as error:
        raise DuplicateMemberError(handle) from error
    return row[0]


def update_member(member_id: int, fields: dict) -> bool:
    """허용 컬럼만 수정 + updated_at 갱신 > 대상 존재 여부"""
    columns = [name for name in UPDATABLE_MEMBER_COLUMNS if name in fields]
    if not columns:
        return find_member(member_id) is not None
    assignments = ', '.join(f'{name} = %s' for name in columns)
    row = execute_audit_sql(f'UPDATE gbrain_member SET {assignments}, updated_at = now() WHERE id = %s RETURNING id',
                            (*[fields[name] for name in columns], member_id), fetch='one')
    return row is not None


def mark_member_ended(member_id: int) -> None:
    execute_audit_sql('UPDATE gbrain_member SET is_active = FALSE, ended_at = now(), updated_at = now() '
                      'WHERE id = %s', (member_id,))


# ---------- 키 ----------
def list_keys(member_id: int = None) -> list:
    sql = f'SELECT {KEY_COLUMNS} FROM gbrain_member_api_key'
    params = ()
    if member_id is not None:
        sql += ' WHERE member_id = %s'
        params = (member_id,)
    sql += ' ORDER BY revoked_at IS NOT NULL, issued_at DESC'
    return [_to_key(row) for row in execute_audit_sql(sql, params, fetch='all')]


def find_key(key_id: int):
    row = execute_audit_sql(f'SELECT {KEY_COLUMNS} FROM gbrain_member_api_key WHERE id = %s', (key_id,), fetch='one')
    return _to_key(row) if row else None


def find_key_secret(key_id: int):
    """다시 보기 전용: 암호문·방식 (없으면 None)"""
    row = execute_audit_sql('SELECT encrypted_token, encryption_scheme FROM gbrain_member_api_key '
                            'WHERE id = %s AND encrypted_token IS NOT NULL', (key_id,), fetch='one')
    return StoredKeySecret(bytes(row[0]), row[1]) if row else None


def list_recorded_token_ids(brain_id: str) -> set:
    rows = execute_audit_sql('SELECT gbrain_token_id FROM gbrain_member_api_key WHERE brain_id = %s',
                             (brain_id,), fetch='all')
    return {row[0] for row in rows}


def insert_key(member_id, brain_id, gbrain_token_id, token_name, scopes,
               encrypted_token=None, encryption_scheme=None) -> int:
    try:
        row = execute_audit_sql(
            'INSERT INTO gbrain_member_api_key (member_id, brain_id, gbrain_token_id, token_name, scopes, '
            'encrypted_token, encryption_scheme) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id',
            (member_id, brain_id, gbrain_token_id, token_name, SCOPE_DELIMITER.join(scopes),
             psycopg2.Binary(encrypted_token) if encrypted_token is not None else None, encryption_scheme),
            fetch='one')
    except psycopg2.errors.UniqueViolation as error:
        raise DuplicateKeyError(gbrain_token_id) from error
    return row[0]


def mark_key_revoked(key_id: int) -> None:
    """폐기 시각 기록 (이미 있으면 유지)"""
    execute_audit_sql('UPDATE gbrain_member_api_key SET revoked_at = COALESCE(revoked_at, now()) WHERE id = %s',
                      (key_id,))


def _to_key(row) -> GbrainMemberApiKey:
    values = list(row)
    values[5] = [scope for scope in (values[5] or '').split(SCOPE_DELIMITER) if scope]
    return GbrainMemberApiKey(*values)
