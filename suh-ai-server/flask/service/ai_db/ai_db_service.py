"""
AI 서버 DB 관리 규칙: 이름 검증, 보호 대상 차단, 삭제 확인, 비번 생성, 연결 문자열 조립, gbrain 팀 브레인
흐름: 검증 > 보호 대상 차단 > 클라이언트 실행 > 결과 (비번은 응답 1회만, 저장·로그 없음)
"""
import logging
import re
import secrets
from urllib.parse import quote

from service.ai_db.ai_db_errors import (
    AiDbError, AiDbUnavailable, ConfirmMismatch, InvalidName, ProtectedObject, SameReaderWriter,
)

logger = logging.getLogger(__name__)

# DB·계정 이름 규칙: 소문자 시작, 소문자·숫자·밑줄, 3~41자
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
# 화면에서 손댈 수 없는 대상 (개인 브레인·시스템·관리 계정)
PROTECTED_DATABASE_NAMES = frozenset({"gbrain", "postgres", "template0", "template1"})
PROTECTED_ROLE_NAMES = frozenset({"gbrain", "postgres", "ai_db_admin"})
PROTECTED_NAME_PREFIX = "pg_"
# 무작위 비번 길이 (token_urlsafe 바이트 수 > 약 40자)
PASSWORD_TOKEN_BYTES = 30


def is_valid_name(name) -> bool:
    return isinstance(name, str) and bool(NAME_PATTERN.match(name))


def is_protected_database(name: str) -> bool:
    return name in PROTECTED_DATABASE_NAMES or name.startswith(PROTECTED_NAME_PREFIX)


def is_protected_role(name: str) -> bool:
    return name in PROTECTED_ROLE_NAMES or name.startswith(PROTECTED_NAME_PREFIX)


def generate_password() -> str:
    return secrets.token_urlsafe(PASSWORD_TOKEN_BYTES)


class AiDbService:
    """client=None 이면 관리 접속 정보 미설정 > 모든 호출 AiDbUnavailable"""

    def __init__(self, client, public_host: str, public_port: int):
        self._client = client
        self.public_host = public_host
        self.public_port = public_port

    # ---- 조회 ----

    def get_status(self) -> dict:
        server_info = self._require_client().server_info()
        return {"is_connected": True, "server_version": server_info.get("server_version"),
                "public_host": self.public_host, "public_port": self.public_port}

    def list_databases(self) -> list:
        return [{**database, "is_protected": is_protected_database(database["name"])}
                for database in self._require_client().list_databases()]

    def list_roles(self) -> list:
        return [{**role, "is_protected": is_protected_role(role["name"])}
                for role in self._require_client().list_roles()]

    # ---- DB ----

    def create_database(self, name, owner_role=None) -> dict:
        """검증 (DB 이름, 선택 계정) > 생성 (vector 확장, PUBLIC 접속 회수, 계정 접속 권한)"""
        client = self._require_client()
        self._validate_database_name(name)
        if owner_role:
            self._validate_role_name(owner_role)
        client.create_database(name, owner_role or None)
        logger.info(f"[ai-db] database created : {name} access={owner_role or '-'}")
        return {"name": name, "owner_role": owner_role or None}

    def delete_database(self, name, confirm_name) -> None:
        client = self._require_client()
        self._validate_database_name(name)
        self._validate_confirm(name, confirm_name)
        client.drop_database(name)
        logger.info(f"[ai-db] database deleted : {name}")

    # ---- 계정 ----

    def create_role(self, name, database_name=None) -> dict:
        """검증 > 무작위 비번으로 생성 > (선택) DB 접속 권한 > 비번·연결 문자열 1회 반환"""
        client = self._require_client()
        self._validate_role_name(name)
        if database_name:
            self._validate_database_name(database_name)
        password = generate_password()
        client.create_role(name, password)
        if database_name:
            self._grant_or_drop_role(client, database_name, name)
        logger.info(f"[ai-db] role created : {name} database={database_name or '-'}")
        return self._build_secret_response(name, password, database_name)

    def reset_password(self, name, database_name=None) -> dict:
        client = self._require_client()
        self._validate_role_name(name)
        if database_name:
            self._validate_database_name(database_name)
        password = generate_password()
        client.set_password(name, password)
        logger.info(f"[ai-db] role password reset : {name}")
        return self._build_secret_response(name, password, database_name)

    def delete_role(self, name, confirm_name) -> None:
        client = self._require_client()
        self._validate_role_name(name)
        self._validate_confirm(name, confirm_name)
        client.drop_role(name)
        logger.info(f"[ai-db] role deleted : {name}")

    # ---- 접속 권한 ----

    def grant(self, database_name, role_name) -> None:
        client = self._require_client()
        self._validate_database_name(database_name)
        self._validate_role_name(role_name)
        client.grant(database_name, role_name)
        logger.info(f"[ai-db] access granted : {role_name} -> {database_name}")

    def revoke(self, database_name, role_name) -> None:
        client = self._require_client()
        self._validate_database_name(database_name)
        self._validate_role_name(role_name)
        client.revoke(database_name, role_name)
        logger.info(f"[ai-db] access revoked : {role_name} -> {database_name}")

    # ---- gbrain 팀 브레인 ----

    def get_gbrain_status(self, database_name) -> dict:
        client = self._require_client()
        self._validate_database_name(database_name)
        return client.get_gbrain_status(database_name)

    def prepare_gbrain(self, database_name, writer_role) -> None:
        """검증 (DB, 쓰기 계정) > 확장·RLS 이벤트 트리거·쓰기 계정 BYPASSRLS"""
        client = self._require_client()
        self._validate_database_name(database_name)
        self._validate_role_name(writer_role)
        client.prepare_gbrain_database(database_name, writer_role)
        logger.info(f"[ai-db] gbrain prepared : {database_name} writer={writer_role}")

    def grant_gbrain_reader(self, database_name, reader_role, writer_role) -> None:
        """검증 (DB, 읽기·쓰기 계정, 서로 다름) > 읽기 전용 권한 (일반 grant 의 CREATE 는 주지 않음)"""
        client = self._require_client()
        self._validate_gbrain_reader(database_name, reader_role, writer_role)
        client.grant_gbrain_reader(database_name, reader_role, writer_role)
        logger.info(f"[ai-db] gbrain reader granted : {reader_role} -> {database_name} writer={writer_role}")

    def revoke_gbrain_reader(self, database_name, reader_role, writer_role) -> None:
        client = self._require_client()
        self._validate_gbrain_reader(database_name, reader_role, writer_role)
        client.revoke_gbrain_reader(database_name, reader_role, writer_role)
        logger.info(f"[ai-db] gbrain reader revoked : {reader_role} -> {database_name} writer={writer_role}")

    # ---- 연결 문자열 ----

    def build_connection_url(self, role_name: str, password: str, database_name: str = None) -> str:
        """postgresql://<계정>:<비번 URL 인코딩>@<외부 주소>:<포트>/<DB>"""
        return (f"postgresql://{role_name}:{quote(password, safe='')}@"
                f"{self.public_host}:{self.public_port}/{database_name or ''}")

    def build_display_url(self, role_name: str, database_name: str = None) -> str:
        """비번 없는 표시용: postgresql://<계정>@<외부 주소>:<포트>/<DB>"""
        return f"postgresql://{role_name}@{self.public_host}:{self.public_port}/{database_name or ''}"

    # ---- 내부 ----

    def _require_client(self):
        if self._client is None:
            raise AiDbUnavailable()
        return self._client

    def _build_secret_response(self, role_name: str, password: str, database_name) -> dict:
        return {"name": role_name, "database": database_name or None, "password": password,
                "connection_url": self.build_connection_url(role_name, password, database_name),
                "display_url": self.build_display_url(role_name, database_name)}

    @staticmethod
    def _grant_or_drop_role(client, database_name: str, role_name: str) -> None:
        """새 계정 접속 권한 실패 시 계정 삭제 후 재발생 (비번 모르는 계정 남기지 않음)"""
        try:
            client.grant(database_name, role_name)
        except AiDbError:
            try:
                client.drop_role(role_name)
            except AiDbError as error:
                logger.warning(f"[ai-db] rollback drop role failed : {role_name} code={error.code}")
            raise

    @staticmethod
    def _validate_database_name(name) -> None:
        """보호 대상 > 이름 규칙 순서"""
        if isinstance(name, str) and is_protected_database(name):
            raise ProtectedObject()
        if not is_valid_name(name):
            raise InvalidName()

    @staticmethod
    def _validate_role_name(name) -> None:
        if isinstance(name, str) and is_protected_role(name):
            raise ProtectedObject()
        if not is_valid_name(name):
            raise InvalidName()

    @classmethod
    def _validate_gbrain_reader(cls, database_name, reader_role, writer_role) -> None:
        """읽기 = 쓰기 계정이면 거부 (빼기 시 쓰기 계정 BYPASSRLS 까지 회수됨)"""
        cls._validate_database_name(database_name)
        cls._validate_role_name(reader_role)
        cls._validate_role_name(writer_role)
        if reader_role == writer_role:
            raise SameReaderWriter()

    @staticmethod
    def _validate_confirm(name: str, confirm_name) -> None:
        if confirm_name != name:
            raise ConfirmMismatch()
