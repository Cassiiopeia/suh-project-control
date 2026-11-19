"""AI 서버 DB 테스트 공통: 가짜 PG 관리 클라이언트 (메모리 DB·계정·권한·gbrain), 가짜를 심은 서비스"""
from __future__ import annotations

from service.ai_db.ai_db_errors import AlreadyExists, DatabaseInUse, GbrainOpsMissing, NotFound
from service.ai_db.ai_db_service import AiDbService

PUBLIC_HOST = "ai.postgres.example.com"
PUBLIC_PORT = 5432


class FakePgAdminClient:
    """호출 기록 + 존재 여부만 흉내 (busy_databases: 접속 중인 DB, ops_missing_databases: ai_db_ops 미설치 DB)"""

    def __init__(self):
        self.databases: dict[str, set] = {"gbrain": {"gbrain"}, "gbrain_elum": {"elum_member"}}
        self.roles: dict[str, str] = {"gbrain": "-", "elum_member": "-", "ai_db_admin": "-"}
        self.busy_databases: set = set()
        self.ops_missing_databases: set = set()
        self.calls: list[tuple] = []

    def server_info(self) -> dict:
        return {"server_version": "17.2"}

    def list_databases(self) -> list:
        return [{"name": name, "owner": "ai_db_admin", "size_bytes": 1024, "access_roles": sorted(access),
                 "is_public_connect": False} for name, access in sorted(self.databases.items())]

    def list_roles(self) -> list:
        return [{"name": name} for name in sorted(self.roles)]

    def create_database(self, name, owner_role=None):
        self.calls.append(("create_database", name, owner_role))
        if name in self.databases:
            raise AlreadyExists()
        self.databases[name] = {owner_role} if owner_role else set()

    def drop_database(self, name):
        self.calls.append(("drop_database", name))
        if name not in self.databases:
            raise NotFound()
        if name in self.busy_databases:
            raise DatabaseInUse()
        del self.databases[name]

    def create_role(self, name, password):
        self.calls.append(("create_role", name))
        if name in self.roles:
            raise AlreadyExists()
        self.roles[name] = password

    def set_password(self, name, password):
        self.calls.append(("set_password", name))
        if name not in self.roles:
            raise NotFound()
        self.roles[name] = password

    def drop_role(self, name):
        self.calls.append(("drop_role", name))
        if name not in self.roles:
            raise NotFound()
        del self.roles[name]

    def grant(self, database_name, role_name):
        self.calls.append(("grant", database_name, role_name))
        if database_name not in self.databases or role_name not in self.roles:
            raise NotFound()
        self.databases[database_name].add(role_name)

    def revoke(self, database_name, role_name):
        self.calls.append(("revoke", database_name, role_name))
        if database_name not in self.databases or role_name not in self.roles:
            raise NotFound()
        self.databases[database_name].discard(role_name)

    def get_gbrain_status(self, database_name):
        self._require_gbrain_database(database_name)
        return {"is_ready": False, "has_ops_functions": True, "has_pages_table": False,
                "writer_role": None, "readers": []}

    def prepare_gbrain_database(self, database_name, writer_role):
        self.calls.append(("prepare_gbrain", database_name, writer_role))
        self._require_gbrain_database(database_name)

    def grant_gbrain_reader(self, database_name, reader_role, writer_role):
        self.calls.append(("grant_gbrain_reader", database_name, reader_role, writer_role))
        self._require_gbrain_database(database_name)

    def revoke_gbrain_reader(self, database_name, reader_role, writer_role):
        self.calls.append(("revoke_gbrain_reader", database_name, reader_role, writer_role))
        self._require_gbrain_database(database_name)

    def _require_gbrain_database(self, database_name):
        if database_name not in self.databases:
            raise NotFound()
        if database_name in self.ops_missing_databases:
            raise GbrainOpsMissing()


def make_service(client=None) -> AiDbService:
    return AiDbService(client, PUBLIC_HOST, PUBLIC_PORT)
