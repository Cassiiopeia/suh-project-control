"""AI 서버 DB 규칙: 이름 검증, 보호 대상 차단, 삭제 확인, 비번 1회 반환, 연결 문자열, 미설정, 클라이언트 SQL 조립"""
from __future__ import annotations

import logging
from urllib.parse import unquote, urlsplit

import psycopg2
import pytest
from psycopg2 import sql

from ai_db_fixtures import PUBLIC_HOST, PUBLIC_PORT, FakePgAdminClient, make_service
from service.ai_db.ai_db_errors import (
    AiDbUnavailable, ConfirmMismatch, DatabaseInUse, InvalidName, NotFound, ProtectedObject,
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
    def __init__(self, statements):
        self.statements = statements

    def execute(self, statement, params=None):
        self.statements.append(statement)

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class RecordingConnection:
    def __init__(self, statements, connect_options):
        self.statements = statements
        self.connect_options = connect_options
        self.autocommit = False

    def cursor(self):
        return RecordingCursor(self.statements)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def make_recording_client():
    statements, connect_options = [], []

    def connect(dsn, **options):
        connect_options.append(options)
        return RecordingConnection(statements, options)
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
