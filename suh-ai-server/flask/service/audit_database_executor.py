"""
관제소 DB(AUDIT_DATABASE_URL) SQL 1건 실행 공통: 연결 > 실행 > 커밋 > 닫기
URL 미설정·접속·쿼리 실패는 AuditDatabaseUnavailableError, 유일 키 충돌은 UniqueViolation 그대로
"""
import psycopg2

from config.db_config import get_audit_database_url

DB_CONNECT_TIMEOUT_SECONDS = 3


class AuditDatabaseUnavailableError(Exception):
    """DB URL 미설정 또는 접속·쿼리 실패"""


def execute_audit_sql(sql: str, params: tuple = (), fetch: str = None):
    """fetch: None / one / all"""
    url = get_audit_database_url()
    if not url:
        raise AuditDatabaseUnavailableError('database url not set')
    try:
        connection = psycopg2.connect(url, connect_timeout=DB_CONNECT_TIMEOUT_SECONDS)
    except psycopg2.Error as error:
        raise AuditDatabaseUnavailableError(f'connect failed: {type(error).__name__}') from error
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            if fetch == 'one':
                return cursor.fetchone()
            if fetch == 'all':
                return cursor.fetchall()
            return None
    except psycopg2.errors.UniqueViolation:
        raise
    except psycopg2.Error as error:
        raise AuditDatabaseUnavailableError(f'query failed: {type(error).__name__}') from error
    finally:
        connection.close()
