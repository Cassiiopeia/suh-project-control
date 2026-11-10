"""
claude_login_account 테이블 접근: 목록, 단건, 추가, 수정, 삭제, 성공·테스트 결과 기록
DB 는 감사로그와 같은 AUDIT_DATABASE_URL, 미설정·다운이면 AccountStoreUnavailableError
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psycopg2

from config.db_config import get_audit_database_url

logger = logging.getLogger(__name__)

DB_CONNECT_TIMEOUT_SECONDS = 3
ACCOUNT_COLUMNS = ("id, gmail_address, display_name, encrypted_app_password, encryption_scheme, "
                   "is_enabled, last_success_at, is_last_test_failed, created_at, updated_at")
# 수정 허용 컬럼 (SQL 조립 시 이 목록 밖 키는 무시)
UPDATABLE_COLUMNS = ("display_name", "encrypted_app_password", "encryption_scheme",
                     "is_enabled", "is_last_test_failed")


class AccountStoreUnavailableError(Exception):
    """DB URL 미설정 또는 접속·쿼리 실패"""


class DuplicateAccountError(Exception):
    """같은 Gmail 주소 이미 등록"""


@dataclass
class ClaudeLoginAccount:
    id: int
    gmail_address: str
    display_name: str
    encrypted_app_password: bytes
    encryption_scheme: str
    is_enabled: bool
    last_success_at: Optional[datetime]
    is_last_test_failed: bool
    created_at: datetime
    updated_at: datetime


def list_accounts(is_enabled_only: bool = False) -> list:
    sql = f"SELECT {ACCOUNT_COLUMNS} FROM claude_login_account"
    if is_enabled_only:
        sql += " WHERE is_enabled"
    sql += " ORDER BY id"
    return [ClaudeLoginAccount(*row) for row in _execute(sql, fetch="all")]


def find_account(account_id: int):
    row = _execute(f"SELECT {ACCOUNT_COLUMNS} FROM claude_login_account WHERE id = %s",
                   (account_id,), fetch="one")
    return ClaudeLoginAccount(*row) if row else None


def insert_account(gmail_address, display_name, encrypted_app_password, encryption_scheme) -> int:
    try:
        row = _execute(
            "INSERT INTO claude_login_account (gmail_address, display_name, encrypted_app_password, "
            "encryption_scheme) VALUES (%s, %s, %s, %s) RETURNING id",
            (gmail_address, display_name, psycopg2.Binary(encrypted_app_password), encryption_scheme),
            fetch="one")
    except psycopg2.errors.UniqueViolation as error:
        raise DuplicateAccountError(gmail_address) from error
    return row[0]


def update_account(account_id: int, fields: dict) -> bool:
    """허용 컬럼만 수정 + updated_at 갱신 > 대상 존재 여부"""
    columns = [name for name in UPDATABLE_COLUMNS if name in fields]
    if not columns:
        return find_account(account_id) is not None
    values = [psycopg2.Binary(fields[name]) if name == "encrypted_app_password" else fields[name]
              for name in columns]
    assignments = ", ".join(f"{name} = %s" for name in columns)
    row = _execute(f"UPDATE claude_login_account SET {assignments}, updated_at = now() "
                   "WHERE id = %s RETURNING id", (*values, account_id), fetch="one")
    return row is not None


def delete_account(account_id: int) -> bool:
    row = _execute("DELETE FROM claude_login_account WHERE id = %s RETURNING id", (account_id,), fetch="one")
    return row is not None


def mark_success(account_id: int):
    """코드 발급 성공 시각 기록 (백그라운드 작업에서 호출, 실패해도 작업 결과 유지)"""
    try:
        _execute("UPDATE claude_login_account SET last_success_at = now() WHERE id = %s", (account_id,))
    except AccountStoreUnavailableError as error:
        logger.warning("[claude login] mark success failed : account=%s %s", account_id, error)


def _execute(sql: str, params: tuple = (), fetch: str = None):
    """연결 > 실행 > 커밋 > 닫기 (fetch: None / one / all)"""
    url = get_audit_database_url()
    if not url:
        raise AccountStoreUnavailableError("database url not set")
    try:
        connection = psycopg2.connect(url, connect_timeout=DB_CONNECT_TIMEOUT_SECONDS)
    except psycopg2.Error as error:
        raise AccountStoreUnavailableError(f"connect failed: {type(error).__name__}") from error
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            if fetch == "one":
                return cursor.fetchone()
            if fetch == "all":
                return cursor.fetchall()
            return None
    except psycopg2.errors.UniqueViolation:
        raise
    except psycopg2.Error as error:
        raise AccountStoreUnavailableError(f"query failed: {type(error).__name__}") from error
    finally:
        connection.close()
