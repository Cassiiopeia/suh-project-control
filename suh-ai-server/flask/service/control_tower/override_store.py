"""관제소 덮어쓰기 저장소 (ControlTowerStore 믹스인): 서비스·프로젝트 덮어쓰기, 사용자 추가 항목, 상태 페이지 설정
_connection·_write_transaction·get_meta·set_meta는 ControlTowerStore가 제공"""
from __future__ import annotations

from datetime import datetime, timezone

from service.control_tower.meta_keys import (
    META_KEY_STATUS_PAGE_NOTICE_LEVEL, META_KEY_STATUS_PAGE_NOTICE_TEXT, META_KEY_STATUS_PAGE_TITLE,
)
from service.control_tower.override_models import (
    PROJECT_OVERRIDE_FIELDS, SERVICE_OVERRIDE_FIELDS, CustomProject, CustomService, ProjectOverride,
    RegistryOverrides, ServiceOverride,
)
from service.control_tower.registry import StatusPage
from service.control_tower.registry_models import DEFAULT_STATUS_PAGE_TITLE, NOTICE_LEVEL_INFO, NOTICE_LEVELS

# 0/1로 저장하는 boolean 칸
BOOLEAN_COLUMNS = ("is_public", "is_hidden")
# 상태 페이지 설정 칸 > meta 키
STATUS_PAGE_META_KEYS = {
    "title": META_KEY_STATUS_PAGE_TITLE,
    "notice_text": META_KEY_STATUS_PAGE_NOTICE_TEXT,
    "notice_level": META_KEY_STATUS_PAGE_NOTICE_LEVEL,
}


def _to_utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _from_utc_text(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _to_column(name: str, value):
    """boolean 칸은 0/1, 나머지는 그대로 (None 유지)"""
    if value is not None and name in BOOLEAN_COLUMNS:
        return int(value)
    return value


def _from_column(row, name: str):
    value = row[name]
    if value is not None and name in BOOLEAN_COLUMNS:
        return bool(value)
    return value


class OverrideStoreMixin:
    # ---- 한 번에 읽기 ----

    def load_registry_overrides(self) -> RegistryOverrides:
        """덮어쓰기 4종 + 상태 페이지 설정 (사용자 추가 항목은 생성 순)"""
        connection = self._connection()
        service_overrides = {
            row["service_id"]: ServiceOverride(
                row["service_id"], *(_from_column(row, name) for name in SERVICE_OVERRIDE_FIELDS),
                _from_utc_text(row["updated_at"]))
            for row in connection.execute("SELECT * FROM service_override").fetchall()
        }
        custom_services = tuple(
            CustomService(row["id"], row["project_id"], row["name"], row["external_url"], row["status"],
                          bool(row["is_public"]), row["sort_order"], _from_utc_text(row["created_at"]))
            for row in connection.execute("SELECT * FROM custom_service ORDER BY created_at, id").fetchall()
        )
        project_overrides = {
            row["project_id"]: ProjectOverride(
                row["project_id"], *(_from_column(row, name) for name in PROJECT_OVERRIDE_FIELDS),
                _from_utc_text(row["updated_at"]))
            for row in connection.execute("SELECT * FROM project_override").fetchall()
        }
        custom_projects = tuple(
            CustomProject(row["id"], row["name"], row["sort_order"], _from_utc_text(row["created_at"]))
            for row in connection.execute("SELECT * FROM custom_project ORDER BY created_at, id").fetchall()
        )
        return RegistryOverrides(service_overrides, custom_services, project_overrides, custom_projects,
                                 self.load_status_page())

    # ---- 덮어쓰기 (changes 값 None = 그 칸 지움, 전부 비면 행 삭제) ----

    def save_service_override(self, service_id: str, changes: dict, now: datetime) -> None:
        self._save_override("service_override", "service_id", SERVICE_OVERRIDE_FIELDS, service_id, changes, now)

    def save_project_override(self, project_id: str, changes: dict, now: datetime) -> None:
        self._save_override("project_override", "project_id", PROJECT_OVERRIDE_FIELDS, project_id, changes, now)

    def _save_override(self, table_name: str, key_column: str, field_names: tuple[str, ...], key: str,
                       changes: dict, now: datetime) -> None:
        """기존 행 읽기 > 바뀐 칸 반영 > 전부 NULL이면 삭제, 아니면 저장 (한 트랜잭션)"""
        with self._write_transaction() as connection:
            row = connection.execute(f"SELECT * FROM {table_name} WHERE {key_column} = ?", (key,)).fetchone()
            values = {name: (row[name] if row is not None else None) for name in field_names}
            values.update({name: _to_column(name, value) for name, value in changes.items() if name in field_names})
            if all(value is None for value in values.values()):
                connection.execute(f"DELETE FROM {table_name} WHERE {key_column} = ?", (key,))
                return
            column_names = (key_column, *field_names, "updated_at")
            placeholders = ",".join("?" for _ in column_names)
            connection.execute(
                f"INSERT OR REPLACE INTO {table_name} ({','.join(column_names)}) VALUES ({placeholders})",
                (key, *(values[name] for name in field_names), _to_utc_text(now)))

    # ---- 사용자 추가 서비스·프로젝트 ----

    def insert_custom_service(self, service: CustomService, now: datetime) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO custom_service VALUES (?,?,?,?,?,?,?,?)",
                (service.id, service.project_id, service.name, service.external_url, service.status,
                 int(service.is_public), service.sort_order, _to_utc_text(now)))

    def delete_custom_service(self, service_id: str) -> bool:
        """사용자 추가 서비스 + 그 덮어쓰기 삭제 > 지운 행이 있었는지"""
        with self._write_transaction() as connection:
            deleted = connection.execute("DELETE FROM custom_service WHERE id = ?", (service_id,)).rowcount
            connection.execute("DELETE FROM service_override WHERE service_id = ?", (service_id,))
            return deleted > 0

    def insert_custom_project(self, project: CustomProject, now: datetime) -> None:
        with self._connection() as connection:
            connection.execute("INSERT INTO custom_project VALUES (?,?,?,?)",
                               (project.id, project.name, project.sort_order, _to_utc_text(now)))

    # ---- 상태 페이지 설정 (meta) ----

    def load_status_page(self) -> StatusPage:
        """meta 3개 > StatusPage (빈 제목·모르는 수준은 기본값)"""
        title = self.get_meta(META_KEY_STATUS_PAGE_TITLE) or DEFAULT_STATUS_PAGE_TITLE
        notice_level = self.get_meta(META_KEY_STATUS_PAGE_NOTICE_LEVEL)
        return StatusPage(title, self.get_meta(META_KEY_STATUS_PAGE_NOTICE_TEXT) or "",
                          notice_level if notice_level in NOTICE_LEVELS else NOTICE_LEVEL_INFO)

    def save_status_page(self, changes: dict) -> None:
        """바뀐 칸만 meta 기록 (None = 기본값으로 되돌림, 빈 문자열 저장)"""
        for name, value in changes.items():
            if name in STATUS_PAGE_META_KEYS:
                self.set_meta(STATUS_PAGE_META_KEYS[name], "" if value is None else value)
