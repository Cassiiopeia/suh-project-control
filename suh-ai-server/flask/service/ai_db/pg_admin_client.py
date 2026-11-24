"""
AI 서버 PG 관리 클라이언트: DB·계정 생성/삭제, 비번 설정, 접속 권한 주기/빼기, gbrain 준비
이름은 sql.Identifier, 비번은 클라이언트에서 SCRAM 해시 후 sql.Literal 로만 조립 (문자열 포맷 금지)
"""
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import encrypt_password

from service.ai_db.ai_db_errors import (
    AiDbError, AiDbUnavailable, AlreadyExists, DatabaseInUse, GbrainOpsMissing, InvalidName, NotFound,
    PermissionDenied, RoleInUse,
)
from service.ai_db.pg_team_brain_client import PgTeamBrainClientMixin

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 3
PASSWORD_ALGORITHM = "scram-sha-256"
# pgcode > 오류 (42P04 duplicate_database, 42710 duplicate_object, 3D000 invalid_catalog_name,
# 42704 undefined_object, 55006 object_in_use, 2BP01 dependent_objects_still_exist, 42501 insufficient_privilege,
# 42602 invalid_name, 42883 undefined_function·3F000 invalid_schema_name = 그 DB 에 ai_db_ops 미설치)
PGCODE_ERRORS = {
    "42P04": AlreadyExists, "42710": AlreadyExists,
    "3D000": NotFound, "42704": NotFound,
    "55006": DatabaseInUse, "2BP01": RoleInUse, "42501": PermissionDenied,
    "42602": InvalidName, "42883": GbrainOpsMissing, "3F000": GbrainOpsMissing,
}
DATABASE_IN_USE_MESSAGE = "is being accessed by other users"

# DB 목록: 템플릿 제외, 크기(접속 권한 있을 때만), 소유자, 명시적 CONNECT 계정, PUBLIC 접속 여부
LIST_DATABASES_SQL = """
SELECT d.datname::text,
       pg_get_userbyid(d.datdba)::text,
       CASE WHEN has_database_privilege(d.oid, 'CONNECT') THEN pg_database_size(d.oid) END,
       COALESCE((SELECT array_agg(DISTINCT r.rolname::text)
                 FROM aclexplode(d.datacl) a JOIN pg_roles r ON r.oid = a.grantee
                 WHERE a.privilege_type = 'CONNECT'), '{}'),
       COALESCE((SELECT bool_or(a.grantee = 0) FROM aclexplode(d.datacl) a
                 WHERE a.privilege_type = 'CONNECT'), d.datacl IS NULL)
FROM pg_database d
WHERE NOT d.datistemplate
ORDER BY d.datname
"""
LIST_ROLES_SQL = "SELECT rolname::text FROM pg_roles WHERE rolcanlogin AND rolname !~ '^pg_' ORDER BY rolname"
DATABASE_EXISTS_SQL = "SELECT 1 FROM pg_database WHERE datname = {}"
# gbrain 상태 (대상 DB 안): ops 스키마, RLS 이벤트 트리거, auto_enable_rls() 소유자(= 쓰기 계정), pages 표
GBRAIN_STATUS_SQL = """
SELECT to_regnamespace('ai_db_ops') IS NOT NULL,
       EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'auto_rls_on_create_table'),
       (SELECT pg_get_userbyid(p.proowner)::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = 'auto_enable_rls' LIMIT 1),
       to_regclass('public.pages') IS NOT NULL
"""
# ai_db_ops 함수 호출 (sql/ai_db_ops_gbrain.sql, 대상 DB 안에서 실행)
GBRAIN_PREPARE_SQL = "SELECT ai_db_ops.prepare_gbrain_database({})"


class PgAdminClient(PgTeamBrainClientMixin):
    """관리 DSN 1개로 동작, 호출마다 연결 > autocommit 실행 > 닫기 (팀 브레인 작업은 PgTeamBrainClientMixin)"""

    def __init__(self, dsn: str, connect=psycopg2.connect):
        self._dsn = dsn
        self._connect = connect

    # ---- 조회 ----

    def server_info(self) -> dict:
        rows = self._fetch(sql.SQL("SELECT current_setting('server_version')"))
        return {"server_version": rows[0][0] if rows else None}

    def list_databases(self) -> list:
        rows = self._fetch(sql.SQL(LIST_DATABASES_SQL))
        return [{"name": name, "owner": owner, "size_bytes": size_bytes,
                 "access_roles": sorted(access_roles or []), "is_public_connect": bool(is_public_connect)}
                for name, owner, size_bytes, access_roles, is_public_connect in rows]

    def list_roles(self) -> list:
        return [{"name": row[0]} for row in self._fetch(sql.SQL(LIST_ROLES_SQL))]

    # ---- DB ----

    def create_database(self, name: str, owner_role: str = None) -> None:
        """DB 생성 > PUBLIC 접속 회수 > vector 확장 > (선택) 계정 접속 권한, 생성 뒤 실패 시 DB 삭제 후 재발생"""
        database = sql.Identifier(name)
        self._execute([sql.SQL("CREATE DATABASE {}").format(database)])
        try:
            self._execute([sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(database)])
            self._execute([sql.SQL("CREATE EXTENSION IF NOT EXISTS vector")], database_name=name)
            if owner_role:
                self.grant(name, owner_role)
        except AiDbError:
            self._drop_database_quietly(name)
            raise

    def drop_database(self, name: str) -> None:
        """WITH (FORCE) 미사용: 접속 중이면 DatabaseInUse"""
        self._execute([sql.SQL("DROP DATABASE {}").format(sql.Identifier(name))])

    # ---- 계정 ----

    def create_role(self, name: str, password: str) -> None:
        self._execute_with_password(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}"), name, password)

    def set_password(self, name: str, password: str) -> None:
        self._execute_with_password(sql.SQL("ALTER ROLE {} PASSWORD {}"), name, password)

    def drop_role(self, name: str) -> None:
        self._execute([sql.SQL("DROP ROLE {}").format(sql.Identifier(name))])

    # ---- 접속 권한 ----

    def grant(self, database_name: str, role_name: str) -> None:
        """CONNECT (DB) > USAGE·CREATE (그 DB public 스키마)"""
        role = sql.Identifier(role_name)
        self._execute([sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database_name), role)])
        self._execute([sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(role)],
                      database_name=database_name)

    def revoke(self, database_name: str, role_name: str) -> None:
        """CONNECT > public 스키마 권한 (CONNECT 먼저: DB·계정 존재를 접속 전에 확인)"""
        role = sql.Identifier(role_name)
        self._execute([sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(database_name), role)])
        self._execute([sql.SQL("REVOKE USAGE, CREATE ON SCHEMA public FROM {}").format(role)],
                      database_name=database_name)

    # ---- gbrain 팀 브레인 (슈퍼유저 작업은 ai_db_ops SECURITY DEFINER 함수로 위임) ----

    def get_gbrain_status(self, database_name: str) -> dict:
        """ops 스키마·이벤트 트리거 둘 다 있어야 준비됨, 쓰기 계정 = auto_enable_rls() 소유자"""
        self._require_database(database_name)
        has_ops_schema, has_event_trigger, writer_role, has_pages_table = \
            self._fetch(sql.SQL(GBRAIN_STATUS_SQL), database_name=database_name)[0]
        return {"is_ready": bool(has_ops_schema and has_event_trigger), "has_ops_functions": bool(has_ops_schema),
                "has_pages_table": bool(has_pages_table), "writer_role": writer_role}

    def prepare_gbrain_database(self, database_name: str, writer_role: str) -> None:
        self._call_gbrain_ops(database_name, GBRAIN_PREPARE_SQL, writer_role)

    # ---- 내부 ----

    def _call_gbrain_ops(self, database_name: str, function_sql: str, *role_names: str) -> None:
        """DB 존재 확인 > 그 DB 접속 > ai_db_ops 함수 (계정 이름은 Literal 인자)"""
        self._require_database(database_name)
        statement = sql.SQL(function_sql).format(*[sql.Literal(name) for name in role_names])
        self._execute([statement], database_name=database_name)

    def _require_database(self, database_name: str) -> None:
        """없는 DB 접속은 pgcode 없는 OperationalError(= unavailable) > 먼저 관리 DB 에서 확인해 NotFound"""
        if not self._fetch(sql.SQL(DATABASE_EXISTS_SQL).format(sql.Literal(database_name))):
            raise NotFound()


    def _execute_with_password(self, statement: sql.SQL, name: str, password: str) -> None:
        """비번은 SCRAM 해시로 바꿔 전송 (서버 문장 로그에 원문 남지 않음)"""
        with self._connection() as connection, connection.cursor() as cursor:
            password_hash = self.encrypt_password(connection, name, password)
            cursor.execute(statement.format(sql.Identifier(name), sql.Literal(password_hash)))

    @staticmethod
    def encrypt_password(connection, name: str, password: str) -> str:
        return encrypt_password(password, name, connection, PASSWORD_ALGORITHM)

    def _execute(self, statements: list, database_name: str = None) -> None:
        with self._connection(database_name) as connection, connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    def _fetch(self, statement, database_name: str = None) -> list:
        with self._connection(database_name) as connection, connection.cursor() as cursor:
            cursor.execute(statement)
            return cursor.fetchall()

    def _drop_database_quietly(self, name: str) -> None:
        try:
            self.drop_database(name)
        except AiDbError as error:
            logger.warning(f"[ai-db] rollback drop failed : database={name} code={error.code}")

    @contextmanager
    def _connection(self, database_name: str = None):
        """연결 (CREATE/DROP DATABASE 위해 autocommit) > psycopg2 오류를 관리 오류로 변환 > 닫기"""
        options = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
        if database_name:
            options["dbname"] = database_name
        try:
            connection = self._connect(self._dsn, **options)
        except psycopg2.Error as error:
            raise _translate_error(error, is_connecting=True) from None
        try:
            connection.autocommit = True
            yield connection
        except psycopg2.Error as error:
            raise _translate_error(error) from None
        finally:
            connection.close()


def _translate_error(error: psycopg2.Error, is_connecting: bool = False) -> AiDbError:
    """pgcode > 관리 오류, 접속 단계·코드 없는 OperationalError > 사용 불가 (로그에 메시지·DSN 미포함)"""
    pgcode = getattr(error, "pgcode", None)
    if pgcode in PGCODE_ERRORS:
        return PGCODE_ERRORS[pgcode]()
    if DATABASE_IN_USE_MESSAGE in str(error):
        return DatabaseInUse()
    if is_connecting or (pgcode is None and isinstance(error, psycopg2.OperationalError)):
        logger.warning(f"[ai-db] connection failed : {type(error).__name__}")
        return AiDbUnavailable()
    logger.warning(f"[ai-db] query failed : {type(error).__name__} pgcode={pgcode}")
    return AiDbError()
