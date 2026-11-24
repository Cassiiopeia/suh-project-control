"""
팀 브레인 DB 작업 (PgAdminClient 에 섞어 씀): 검사(카탈로그만), DB·계정 생성, 쓰기 계정 권한 재적용, 슈퍼유저 손보기
지우는 문장 없음 (#226): 실패하면 그대로 두고 다시 실행할 때 받아 씀, 이름은 sql.Identifier·sql.Literal 로만 조립
"""
from psycopg2 import sql

# 관리 DB 에서: 호출 계정, DB 소유자, 호출 계정의 CONNECT 가능 여부
TEAM_DATABASE_SQL = """
SELECT current_user::text, pg_get_userbyid(d.datdba)::text, has_database_privilege(current_user, d.oid, 'CONNECT')
FROM pg_database d WHERE d.datname = {}
"""
# 쓰기 계정: 로그인 가능, 슈퍼유저, 호출 계정이 ADMIN 으로 관리하는지
TEAM_WRITER_ROLE_SQL = """
SELECT r.rolcanlogin, r.rolsuper,
       EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles caller ON caller.oid = m.member
               WHERE m.roleid = r.oid AND caller.rolname = current_user AND m.admin_option)
FROM pg_roles r WHERE r.rolname = {}
"""
# 대상 DB 안 객체 (카탈로그만, 표 데이터는 읽지 않음)
# ops 스키마, RLS 이벤트 트리거, auto_enable_rls() 소유자, pages 표, 그 외 스키마, public 관계 수,
# 쓰기 계정 아닌 소유자, 쓰기 계정 아닌 소유의 public 함수 수 (확장 소속·auto_enable_rls 제외)
TEAM_DATABASE_OBJECTS_SQL = """
SELECT to_regnamespace('ai_db_ops') IS NOT NULL,
       EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'auto_rls_on_create_table'),
       (SELECT pg_get_userbyid(p.proowner)::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = 'auto_enable_rls' LIMIT 1),
       to_regclass('public.pages') IS NOT NULL,
       COALESCE((SELECT array_agg(n.nspname::text ORDER BY n.nspname) FROM pg_namespace n
                 WHERE n.nspname NOT IN ('public', 'ai_db_ops', 'information_schema') AND n.nspname !~ '^pg_'), '{{}}'),
       (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')),
       COALESCE((SELECT array_agg(DISTINCT pg_get_userbyid(c.relowner)::text) FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                   AND pg_get_userbyid(c.relowner) <> {writer}), '{{}}'),
       (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname <> 'auto_enable_rls' AND pg_get_userbyid(p.proowner) <> {writer}
          AND NOT EXISTS (SELECT 1 FROM pg_depend d
                          WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'))
"""
# 호출 계정이 소유한 public 관계 (쓰기 계정에 권한을 줄 수 있는 대상, 보통 0개)
CALLER_OWNED_RELATIONS_SQL = """
SELECT c.relname::text, c.relkind = 'S' FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
"""


class PgTeamBrainClientMixin:
    """PgAdminClient 의 _fetch·_connection 을 씀 (관리 DSN 이든 슈퍼유저 DSN 이든 같은 문장)"""

    # ---- 검사 ----

    def inspect_team_database(self, database_name: str, writer_role: str) -> dict:
        """DB 존재·소유자·접속 가능 > (접속 가능하면) 안 객체, 없으면 exists False"""
        rows = self._fetch(sql.SQL(TEAM_DATABASE_SQL).format(sql.Literal(database_name)))
        if not rows:
            return {'exists': False}
        caller_role, owner, can_connect = rows[0]
        inspection = {'exists': True, 'caller_role': caller_role, 'owner': owner, 'can_connect': bool(can_connect),
                      'is_inspected': False}
        if not can_connect:
            return inspection
        objects_sql = sql.SQL(TEAM_DATABASE_OBJECTS_SQL).format(writer=sql.Literal(writer_role))
        (has_ops_schema, has_event_trigger, rls_function_owner, has_pages_table, extra_schemas,
         public_relation_count, foreign_relation_owners, foreign_function_count) = \
            self._fetch(objects_sql, database_name=database_name)[0]
        inspection.update({
            'is_inspected': True, 'has_ops_schema': bool(has_ops_schema), 'has_event_trigger': bool(has_event_trigger),
            'rls_function_owner': rls_function_owner, 'has_pages_table': bool(has_pages_table),
            'extra_schemas': sorted(extra_schemas or []), 'public_relation_count': int(public_relation_count or 0),
            'foreign_relation_owners': sorted(foreign_relation_owners or []),
            'foreign_function_count': int(foreign_function_count or 0),
        })
        return inspection

    def inspect_team_writer_role(self, role_name: str) -> dict:
        rows = self._fetch(sql.SQL(TEAM_WRITER_ROLE_SQL).format(sql.Literal(role_name)))
        if not rows:
            return {'exists': False}
        can_login, is_superuser, is_managed = rows[0]
        return {'exists': True, 'can_login': bool(can_login), 'is_superuser': bool(is_superuser),
                'is_managed': bool(is_managed)}

    # ---- 생성 (되돌리기 없음: 남은 DB·계정은 다음 실행이 받아 씀) ----

    def create_team_database(self, name: str) -> None:
        """DB 생성 (template1 복사 = ai_db_ops·vector 포함) > PUBLIC 접속 회수"""
        database = sql.Identifier(name)
        self._execute([sql.SQL("CREATE DATABASE {}").format(database)])
        self._execute([sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(database)])

    # ---- 쓰기 계정 권한 (매 실행 재적용, 이미 있으면 그대로) ----

    def apply_team_writer_grants(self, database_name: str, writer_role: str) -> None:
        """CONNECT > public USAGE·CREATE > 호출 계정 소유 표·시퀀스 ALL > 기본 권한(호출 계정이 만들 표·시퀀스)"""
        role = sql.Identifier(writer_role)
        self._execute([sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database_name), role)])
        with self._connection(database_name) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(role))
            cursor.execute(sql.SQL(CALLER_OWNED_RELATIONS_SQL))
            for relation_name, is_sequence in cursor.fetchall():
                object_kind = sql.SQL("SEQUENCE" if is_sequence else "TABLE")
                cursor.execute(sql.SQL("GRANT ALL PRIVILEGES ON {} {} TO {}").format(
                    object_kind, sql.Identifier('public', relation_name), role))
            cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {}").format(role))
            cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {}").format(role))

    # ---- 슈퍼유저 손보기 (빈 DB·gbrain DB 로 판정된 뒤에만 호출) ----

    def change_team_database_owner(self, database_name: str, owner_role: str) -> None:
        """DB 소유자 > 관리 계정 (public 스키마 소유도 pg_database_owner 로 따라감)"""
        self._execute([sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
            sql.Identifier(database_name), sql.Identifier(owner_role))])

    def run_sql_script(self, database_name: str, script_text: str) -> None:
        """대상 DB 에서 SQL 파일 원문 실행 (인자 없음 > % 치환 없음)"""
        with self._connection(database_name) as connection, connection.cursor() as cursor:
            cursor.execute(script_text)
