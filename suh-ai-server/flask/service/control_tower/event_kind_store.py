"""관제소 사용자 정의 알림 종류 저장소 (ControlTowerStore 믹스인): 프로젝트별 종류 조회·추가·삭제
_connection·_write_transaction은 ControlTowerStore가 제공"""
from __future__ import annotations

from datetime import datetime

from service.control_tower.registry_models import EventKindSpec
from service.control_tower.utc_text import to_utc_text

# visible_to 칸 구분자 (빈 문자열 = 관리자만)
VISIBLE_TO_DELIMITER = ","


class EventKindStoreMixin:
    def list_project_event_kinds(self) -> dict[str, tuple[EventKindSpec, ...]]:
        """프로젝트 id > 종류 목록 (생성 순)"""
        rows = self._connection().execute(
            "SELECT project_id, kind, channel_name, visible_to FROM project_event_kind "
            "ORDER BY created_at, rowid").fetchall()
        specs_by_project: dict[str, list[EventKindSpec]] = {}
        for row in rows:
            visible_to = tuple(row["visible_to"].split(VISIBLE_TO_DELIMITER)) if row["visible_to"] else ()
            specs_by_project.setdefault(row["project_id"], []).append(
                EventKindSpec(row["kind"], row["channel_name"], visible_to))
        return {project_id: tuple(specs) for project_id, specs in specs_by_project.items()}

    def insert_project_event_kind(self, project_id: str, spec: EventKindSpec, now: datetime) -> bool:
        """종류 1개 추가 > 이미 있으면 False"""
        with self._write_transaction() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO project_event_kind (project_id, kind, channel_name, visible_to, created_at) "
                "VALUES (?,?,?,?,?)",
                (project_id, spec.kind, spec.channel_name, VISIBLE_TO_DELIMITER.join(spec.visible_to),
                 to_utc_text(now))).rowcount
            return inserted > 0

    def delete_project_event_kind(self, project_id: str, kind: str) -> bool:
        """종류 1개 삭제 > 지운 행이 있었는지"""
        with self._write_transaction() as connection:
            deleted = connection.execute(
                "DELETE FROM project_event_kind WHERE project_id = ? AND kind = ?", (project_id, kind)).rowcount
            return deleted > 0
