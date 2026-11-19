"""AI 서버 DB 규칙: 이름 검증, 보호 대상 차단, 삭제 확인, 비번 1회 반환, 연결 문자열, 미설정, 클라이언트 SQL 조립, gbrain"""
from __future__ import annotations

import logging
from urllib.parse import unquote, urlsplit

import psycopg2
import pytest
from psycopg2 import sql

from ai_db_fixtures import PUBLIC_HOST, PUBLIC_PORT, FakePgAdminClient, make_service
from service.ai_db.ai_db_errors import (
    AiDbUnavailable, ConfirmMismatch, DatabaseInUse, GbrainOpsMissing, InvalidName, NotFound, ProtectedObject,
    SameReaderWriter,
)
from service.ai_db.pg_admin_client import PgAdminClient


@pytest.fixture
def client():
    return FakePgAdminClient()


@pytest.fixture
def service(client):
    return make_service(client)


# ---- 이름 검증·보호 대상 ----

@pytest.mark.parametrize("name", ["ab", "1abc", "Abc", "abc-def", 'x"; drop', "a" * 42, "", None, 123])
def test_이름_규칙_위반은_invalid_name(service, client, name):
    with pytest.raises(InvalidName):
        service.create_database(name)
    assert client.calls == []


@pytest.mark.parametrize("name", ["gbrain", "postgres", "template0", "template1", "pg_x"])
def test_보호_DB는_만들기_삭제_권한_모두_차단(service, client, name):
    with pytest.raises(ProtectedObject):
        service.create_database(name)
    with pytest.raises(ProtectedObject):
        service.delete_database(name, name)
    with pytest.raises(ProtectedObject):
        service.grant(name, "elum_member")
    assert client.calls == []


@pytest.mark.parametrize("name", ["gbrain", "postgres", "ai_db_admin", "pg_x"])
def test_보호_계정은_비번_재발급_삭제_권한_모두_차단(service, client, name):
    with pytest.raises(ProtectedObject):
        service.reset_password(name)
    with pytest.raises(ProtectedObject):
        service.delete_role(name, name)
    with pytest.raises(ProtectedObject):
        service.revoke("gbrain_elum", name)
    assert client.calls == []


def test_목록은_보호_대상을_표시한다(service):
    databases = {database["name"]: database["is_protected"] for database in service.list_databases()}
    roles = {role["name"]: role["is_protected"] for role in service.list_roles()}

    assert databases == {"gbrain": True, "gbrain_elum": False}
    assert roles == {"ai_db_admin": True, "elum_member": False, "gbrain": True}


# ---- 삭제 확인 ----

def test_삭제는_확인_이름이_같아야_실행(service, client):
    with pytest.raises(ConfirmMismatch):
        service.delete_database("gbrain_elum", "gbrain_elu")
    with pytest.raises(ConfirmMismatch):
        service.delete_role("elum_member", None)
    assert client.calls == []

    service.delete_database("gbrain_elum", "gbrain_elum")
    assert "gbrain_elum" not in client.databases


def test_접속_중인_DB_삭제는_DatabaseInUse(service, client):
    client.busy_databases.add("gbrain_elum")
    with pytest.raises(DatabaseInUse):
        service.delete_database("gbrain_elum", "gbrain_elum")


# ---- 비번·연결 문자열 ----

def test_계정_만들기는_무작위_비번과_연결_문자열을_돌려주고_로그에_비번이_없다(service, client, caplog):
    caplog.set_level(logging.DEBUG)

    secret = service.create_role("team_a", "gbrain_elum")

    assert len(secret["password"]) >= 40
    assert client.roles["team_a"] == secret["password"]
    assert ("grant", "gbrain_elum", "team_a") in client.calls
    parsed = urlsplit(secret["connection_url"])
    assert (parsed.username, unquote(parsed.password), parsed.hostname, parsed.port, parsed.path) == \
        ("team_a", secret["password"], PUBLIC_HOST, PUBLIC_PORT, "/gbrain_elum")
    assert secret["display_url"] == f"postgresql://team_a@{PUBLIC_HOST}:{PUBLIC_PORT}/gbrain_elum"
    assert secret["password"] not in caplog.text


def test_비번은_매번_다르다(service):
    first = service.reset_password("elum_member")["password"]
    second = service.reset_password("elum_member")["password"]
    assert first != second


def test_계정_만든_뒤_권한_실패하면_계정을_지운다(service, client):
    with pytest.raises(NotFound):
        service.create_role("team_b", "no_such_db")
    assert "team_b" not in client.roles


# ---- 미설정 ----

def test_관리_접속_정보가_없으면_모든_호출이_unavailable():
    service = make_service(None)
    for call in (service.get_status, service.list_databases, lambda: service.create_role("team_a")):
        with pytest.raises(AiDbUnavailable):
            call()


# ---- 클라이언트 SQL 조립 ----

class RecordingCursor:
    """fetch_rows: 조회 결과 (기본 빈 목록, DB 존재 확인 통과용 [(1,)])"""

    def __init__(self, statements, fetch_rows=()):
        self.statements = statements
        self.fetch_rows = list(fetch_rows)

    def execute(self, statement, params=None):
        self.statements.append(statement)

    def fetchall(self):
        return self.fetch_rows

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class RecordingConnection:
    def __init__(self, statements, connect_options, fetch_rows=()):
        self.statements = statements
        self.connect_options = connect_options
        self.fetch_rows = fetch_rows
        self.autocommit = False

    def cursor(self):
        return RecordingCursor(self.statements, self.fetch_rows)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def make_recording_client(fetch_rows=()):
    statements, connect_options = [], []

    def connect(dsn, **options):
        connect_options.append(options)
        return RecordingConnection(statements, options, fetch_rows)
    return PgAdminClient("postgresql://admin@127.0.0.1/postgres", connect=connect), statements, connect_options


def identifiers_of(statement) -> list:
    return [part.string for part in statement.seq if isinstance(part, sql.Identifier)]


def test_이름은_Identifier로만_조립된다():
    pg_client, statements, connect_options = make_recording_client()

    pg_client.grant('x"; drop', "team_a")

    assert all(isinstance(statement, sql.Composed) for statement in statements)
    assert identifiers_of(statements[0]) == ['x"; drop', "team_a"]
    assert connect_options[1]["dbname"] == 'x"; drop'
    assert all(options["connect_timeout"] == 3 for options in connect_options)


def test_비번은_해시를_Literal로_넣는다(monkeypatch):
    pg_client, statements, _ = make_recording_client()
    monkeypatch.setattr(PgAdminClient, "encrypt_password", staticmethod(lambda connection, name, password: "SCRAM-SHA-256$hash"))

    pg_client.create_role("team_a", "plain-secret")

    literals = [part.wrapped for part in statements[0].seq if isinstance(part, sql.Literal)]
    assert literals == ["SCRAM-SHA-256$hash"]
    assert "plain-secret" not in repr(statements[0])


def test_접속_실패는_unavailable():
    def failing_connect(dsn, **options):
        raise psycopg2.OperationalError("could not connect")
    pg_client = PgAdminClient("postgresql://admin@127.0.0.1/postgres", connect=failing_connect)

    with pytest.raises(AiDbUnavailable):
        pg_client.list_roles()


class FakePgError(psycopg2.ProgrammingError):
    """pgcode 지정 가능한 psycopg2 오류"""

    def __init__(self, pgcode):
        super().__init__("failed")
        self._pgcode = pgcode

    @property
    def pgcode(self):
        return self._pgcode


@pytest.mark.parametrize("pgcode,expected", [("42P04", "already_exists"), ("42710", "already_exists"),
                                             ("3D000", "not_found"), ("42704", "not_found"),
                                             ("55006", "database_in_use"), ("2BP01", "role_in_use")])
def test_pgcode는_관리_오류로_바뀐다(pgcode, expected):
    class FailingCursor(RecordingCursor):
        def execute(self, statement, params=None):
            raise FakePgError(pgcode)

    class FailingConnection(RecordingConnection):
        def cursor(self):
            return FailingCursor(self.statements)
    pg_client = PgAdminClient("dsn", connect=lambda dsn, **options: FailingConnection([], options))

    with pytest.raises(Exception) as raised:
        pg_client.drop_database("team_db")
    assert raised.value.code == expected


# ---- gbrain 팀 브레인 ----

@pytest.mark.parametrize("database_name,reader_role,writer_role", [
    ("gbrain", "team_a", "elum_member"), ("template1", "team_a", "elum_member"),
    ("gbrain_elum", "gbrain", "elum_member"), ("gbrain_elum", "postgres", "elum_member"),
    ("gbrain_elum", "team_a", "ai_db_admin"), ("gbrain_elum", "team_a", "gbrain"),
])
def test_gbrain_보호_DB와_보호_계정은_읽기_쓰기_어느_쪽도_차단(service, client, database_name, reader_role, writer_role):
    with pytest.raises(ProtectedObject):
        service.grant_gbrain_reader(database_name, reader_role, writer_role)
    with pytest.raises(ProtectedObject):
        service.revoke_gbrain_reader(database_name, reader_role, writer_role)
    assert client.calls == []


def test_gbrain_준비는_보호_쓰기_계정과_잘못된_이름을_막는다(service, client):
    with pytest.raises(ProtectedObject):
        service.prepare_gbrain("gbrain_elum", "ai_db_admin")
    with pytest.raises(InvalidName):
        service.prepare_gbrain("gbrain_elum", 'x"; drop')
    with pytest.raises(InvalidName):
        service.prepare_gbrain("gbrain_elum", None)
    assert client.calls == []


def test_gbrain_읽기_계정이_쓰기_계정과_같으면_거부(service, client):
    with pytest.raises(SameReaderWriter):
        service.revoke_gbrain_reader("gbrain_elum", "elum_member", "elum_member")
    assert client.calls == []


def test_gbrain_읽기_권한은_일반_grant를_쓰지_않는다(service, client):
    service.grant_gbrain_reader("gbrain_elum", "team_a", "elum_member")
    assert client.calls == [("grant_gbrain_reader", "gbrain_elum", "team_a", "elum_member")]


def test_gbrain_함수는_대상_DB에서_Literal_인자로_호출된다():
    pg_client, statements, connect_options = make_recording_client(fetch_rows=[(1,)])

    pg_client.grant_gbrain_reader("gbrain_elum", "team_a", 'x"; drop')

    call = statements[-1]
    assert "ai_db_ops.grant_gbrain_reader" in repr(call)
    assert [part.wrapped for part in call.seq if isinstance(part, sql.Literal)] == ["team_a", 'x"; drop']
    assert connect_options[-1]["dbname"] == "gbrain_elum"


def test_gbrain_없는_DB는_접속_전에_NotFound():
    pg_client, statements, connect_options = make_recording_client()
    with pytest.raises(NotFound):
        pg_client.prepare_gbrain_database("no_such_db", "team_a")
    assert all("dbname" not in options for options in connect_options)


@pytest.mark.parametrize("pgcode,expected", [("42883", "gbrain_ops_missing"), ("42602", "invalid_name"),
                                             ("42501", "permission_denied")])
def test_gbrain_함수_오류_pgcode_변환(pgcode, expected):
    class FailingOnFunctionCursor(RecordingCursor):
        def execute(self, statement, params=None):
            if "ai_db_ops" in repr(statement):
                raise FakePgError(pgcode)

    class FailingConnection(RecordingConnection):
        def cursor(self):
            return FailingOnFunctionCursor(self.statements, [(1,)])
    pg_client = PgAdminClient("dsn", connect=lambda dsn, **options: FailingConnection([], options))

    with pytest.raises(Exception) as raised:
        pg_client.prepare_gbrain_database("gbrain_elum", "team_a")
    assert raised.value.code == expected


@pytest.mark.parametrize("status_row,readers,expected_is_ready", [
    ((False, False, None, False), [], False),                       # ops 스키마·트리거 없음 > 오류 아님
    ((True, True, "elum_member", True), ["elum_member", "team_a"], True),
])
def test_gbrain_상태는_ops_트리거_둘_다_있어야_준비됨이고_쓰기_계정은_읽기에서_뺀다(status_row, readers, expected_is_ready):
    # 조회 순서: DB 존재 확인 > 상태 > 읽기 팀원
    fetch_results = [[(1,)], [status_row], [(reader,) for reader in readers]]

    class QueueCursor(RecordingCursor):
        def fetchall(self):
            return fetch_results.pop(0)

    class QueueConnection(RecordingConnection):
        def cursor(self):
            return QueueCursor(self.statements)
    pg_client = PgAdminClient("dsn", connect=lambda dsn, **options: QueueConnection([], options))

    status = pg_client.get_gbrain_status("gbrain_elum")
    assert status["is_ready"] is expected_is_ready
    assert status["readers"] == ([] if not readers else ["team_a"])


def test_ops_미설치면_GbrainOpsMissing(service, client):
    client.ops_missing_databases.add("gbrain_elum")
    with pytest.raises(GbrainOpsMissing):
        service.prepare_gbrain("gbrain_elum", "elum_member")


# ---- 설정 ----

def test_관리_접속_정보는_환경변수_다음_파일_없으면_None(monkeypatch, tmp_path):
    from config import ai_db_config
    secret_file = tmp_path / "ai-db-admin-url"
    monkeypatch.delenv("AI_DB_ADMIN_URL", raising=False)
    monkeypatch.setenv("AI_DB_ADMIN_URL_FILE", str(tmp_path / "missing"))
    assert ai_db_config.get_admin_url() is None

    secret_file.write_text("  postgresql://from-file  \n", encoding="utf-8")
    monkeypatch.setenv("AI_DB_ADMIN_URL_FILE", str(secret_file))
    assert ai_db_config.get_admin_url() == "postgresql://from-file"

    monkeypatch.setenv("AI_DB_ADMIN_URL", "postgresql://from-env")
    assert ai_db_config.get_admin_url() == "postgresql://from-env"
