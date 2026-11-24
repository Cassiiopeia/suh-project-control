"""팀 브레인 PG 작업 #226: 검사 SQL(Literal·대상 DB), DB 생성 되돌리기 없음, 권한 재적용 문장, 슈퍼유저 손보기, 3F000 변환"""
import psycopg2
import pytest
from psycopg2 import sql

from service.ai_db.ai_db_errors import AiDbError, AiDbUnavailable, GbrainOpsMissing, PermissionDenied
from service.ai_db.pg_admin_client import PgAdminClient
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_database_repair import GbrainTeamDatabaseRepair


class ScriptedCursor:
    """fetch_queue: execute 마다 다음 fetchall 결과, fail_when: 문장에 이 글자가 있으면 오류"""

    def __init__(self, log, fetch_queue, fail_when=None):
        self.log, self.fetch_queue, self.fail_when = log, fetch_queue, fail_when
        self.last_rows = []

    def execute(self, statement, params=None):
        text = statement if isinstance(statement, str) else repr(statement)
        self.log.append(statement)
        if self.fail_when and self.fail_when[0] in text:
            raise self.fail_when[1]
        self.last_rows = self.fetch_queue.pop(0) if self.fetch_queue else []

    def fetchall(self):
        return self.last_rows

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class ScriptedConnection:
    def __init__(self, log, fetch_queue, options, fail_when):
        self.log, self.fetch_queue, self.options, self.fail_when = log, fetch_queue, options, fail_when
        self.autocommit = False

    def cursor(self):
        return ScriptedCursor(self.log, self.fetch_queue, self.fail_when)

    def close(self):
        pass


def make_client(fetch_queue=None, fail_when=None):
    log, options_log = [], []
    queue = list(fetch_queue or [])

    def connect(dsn, **options):
        options_log.append(options)
        return ScriptedConnection(log, queue, options, fail_when)
    return PgAdminClient('postgresql://admin@127.0.0.1/postgres', connect=connect), log, options_log


class FakePgError(psycopg2.ProgrammingError):
    def __init__(self, pgcode):
        super().__init__('failed')
        self._pgcode = pgcode

    @property
    def pgcode(self):
        return self._pgcode


def literals_of(statement) -> list:
    return [part.wrapped for part in statement.seq if isinstance(part, sql.Literal)]


# ---------- 검사 ----------
def test_없는_DB_검사는_대상_DB_에_접속하지_않는다():
    client, log, options_log = make_client(fetch_queue=[[]])

    assert client.inspect_team_database('gbrain_new', 'new_writer') == {'exists': False}
    assert len(options_log) == 1 and 'dbname' not in options_log[0]


def test_DB_검사는_Literal_이름으로_관리_DB_와_대상_DB_카탈로그만_본다():
    objects_row = (True, True, 'elum_writer', True, [], 188, [], 0)
    client, log, options_log = make_client(fetch_queue=[[('ai_db_admin', 'ai_db_admin', True)], [objects_row]])

    inspection = client.inspect_team_database('gbrain_elum', 'elum_writer')

    assert literals_of(log[0]) == ['gbrain_elum'] and 'elum_writer' in literals_of(log[1])
    assert options_log[1]['dbname'] == 'gbrain_elum'
    assert inspection['is_inspected'] and inspection['public_relation_count'] == 188
    assert inspection['rls_function_owner'] == 'elum_writer' and inspection['caller_role'] == 'ai_db_admin'
    # 표 데이터를 읽는 문장 없음 (카탈로그 함수·pg_* 만)
    assert 'public.pages' not in repr(log[1]).replace("to_regclass('public.pages')", '')


def test_관리_계정이_접속_못_하는_DB_는_안을_보지_않는다():
    client, log, options_log = make_client(fetch_queue=[[('ai_db_admin', 'gbrain', False)]])

    inspection = client.inspect_team_database('gbrain_elum', 'elum_writer')

    assert inspection == {'exists': True, 'caller_role': 'ai_db_admin', 'owner': 'gbrain', 'can_connect': False,
                          'is_inspected': False}
    assert len(options_log) == 1


def test_쓰기_계정_검사는_관리_여부를_돌려준다():
    client, _, _ = make_client(fetch_queue=[[(True, False, True)]])

    assert client.inspect_team_writer_role('elum_writer') == {
        'exists': True, 'can_login': True, 'is_superuser': False, 'is_managed': True}


# ---------- 생성·권한 ----------
def test_팀_DB_생성은_실패해도_되돌려_지우지_않는다():
    client, log, _ = make_client(fail_when=('REVOKE', FakePgError('42501')))

    with pytest.raises(PermissionDenied):
        client.create_team_database('gbrain_romrom')

    assert not any('DROP' in repr(statement) for statement in log)


def test_쓰기_계정_권한은_접속_스키마_소유_객체_기본_권한을_모두_다시_준다():
    client, log, options_log = make_client(fetch_queue=[[], [], [('legacy_table', False), ('legacy_seq', True)]])

    client.apply_team_writer_grants('gbrain_elum', 'elum_writer')

    texts = [repr(statement) for statement in log]
    assert 'GRANT CONNECT ON DATABASE' in texts[0] and "Identifier('elum_writer')" in texts[0]
    assert options_log[1]['dbname'] == 'gbrain_elum'
    assert any('GRANT USAGE, CREATE ON SCHEMA public' in text for text in texts)
    assert any("SQL('TABLE')" in text and 'legacy_table' in text for text in texts)
    assert any("SQL('SEQUENCE')" in text and 'legacy_seq' in text for text in texts)
    assert sum('ALTER DEFAULT PRIVILEGES' in text for text in texts) == 2
    assert not any('DROP' in text or 'REVOKE' in text for text in texts)


def test_ops_스키마가_없을_때_3F000_은_gbrain_ops_missing():
    client, _, _ = make_client(fetch_queue=[[(1,)]], fail_when=('ai_db_ops', FakePgError('3F000')))

    with pytest.raises(GbrainOpsMissing):
        client.prepare_gbrain_database('gbrain_elum', 'elum_writer')


# ---------- 슈퍼유저 손보기 ----------
def test_손보기는_소유자_변경과_준비_SQL_파일을_대상_DB_에서_실행한다(tmp_path):
    script_path = tmp_path / 'ops.sql'
    script_path.write_text("CREATE SCHEMA IF NOT EXISTS ai_db_ops AUTHORIZATION gbrain; SELECT '%I';", encoding='utf-8')
    client, log, options_log = make_client()
    repair = GbrainTeamDatabaseRepair(superuser_client_factory=lambda: client, ops_sql_path=str(script_path))

    repair.repair('gbrain_elum', 'ai_db_admin', ['owner_changed', 'ops_installed'])

    assert 'ALTER DATABASE' in repr(log[0]) and "Identifier('ai_db_admin')" in repr(log[0])
    assert log[1] == script_path.read_text(encoding='utf-8') and options_log[1]['dbname'] == 'gbrain_elum'


def test_손보기_SQL_실패는_team_database_repair_failed_와_원인():
    client, _, _ = make_client(fail_when=('ALTER DATABASE', FakePgError('42501')))
    repair = GbrainTeamDatabaseRepair(superuser_client_factory=lambda: client)

    with pytest.raises(GbrainServerError) as error_info:
        repair.repair('gbrain_elum', 'ai_db_admin', ['owner_changed'])

    assert (error_info.value.code, error_info.value.details['cause']) == ('team_database_repair_failed',
                                                                          'permission_denied')


def test_슈퍼유저_접속_정보가_없으면_team_database_repair_unavailable():
    def missing_config():
        raise GbrainServerError('개인 gbrain 설정 파일을 읽지 못했어요', 'personal_config_unreadable', 500)
    repair = GbrainTeamDatabaseRepair(superuser_client_factory=missing_config)

    with pytest.raises(GbrainServerError) as error_info:
        repair.inspect_team_database('gbrain_elum', 'elum_writer')

    assert (error_info.value.code, error_info.value.status_code) == ('team_database_repair_unavailable', 409)
    assert error_info.value.details['cause'] == 'personal_config_unreadable'


def test_슈퍼유저_접속_실패도_team_database_repair_unavailable():
    class UnavailableClient:
        def inspect_team_database(self, *args):
            raise AiDbUnavailable()
    repair = GbrainTeamDatabaseRepair(superuser_client_factory=UnavailableClient)

    with pytest.raises(GbrainServerError) as error_info:
        repair.inspect_team_database('gbrain_elum', 'elum_writer')

    assert error_info.value.code == 'team_database_repair_unavailable'
    assert isinstance(AiDbUnavailable(), AiDbError)
