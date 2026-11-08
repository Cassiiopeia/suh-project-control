"""관제소 프로젝트 썸네일 저장소 (ControlTowerStore 믹스인): 이미지 저장·삭제·조회, 기본 이미지 가져오기 완료 표시
_connection·_write_transaction·get_meta·set_meta는 ControlTowerStore가 제공"""
from __future__ import annotations

from datetime import datetime, timezone

# meta 키 접두사: 기본 이미지 가져오기를 끝낸 프로젝트 (삭제해도 다시 가져오지 않기 위한 표시)
ICON_SEEDED_META_PREFIX = "project_icon_seeded:"


class ProjectIconStoreMixin:
    def save_project_icon(self, project_id: str, image_webp: bytes, content_hash: str, now: datetime) -> None:
        """프로젝트 썸네일 저장 (있으면 교체)"""
        with self._write_transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO project_icon (project_id, image_webp, content_hash, updated_at) VALUES (?,?,?,?)",
                (project_id, image_webp, content_hash, now.astimezone(timezone.utc).isoformat(timespec="microseconds")))

    def delete_project_icon(self, project_id: str) -> bool:
        """썸네일 삭제 > 지운 행이 있었는지"""
        with self._write_transaction() as connection:
            return connection.execute("DELETE FROM project_icon WHERE project_id = ?", (project_id,)).rowcount > 0

    def load_project_icon_images(self) -> dict[str, bytes]:
        """project_id > 128px WebP 바이트"""
        rows = self._connection().execute("SELECT project_id, image_webp FROM project_icon").fetchall()
        return {row["project_id"]: bytes(row["image_webp"]) for row in rows}

    def load_project_icon_versions(self) -> dict[str, str]:
        """project_id > 내용 해시 12자 (스냅샷 버전용, 이미지 바이트는 읽지 않음)"""
        rows = self._connection().execute("SELECT project_id, content_hash FROM project_icon").fetchall()
        return {row["project_id"]: row["content_hash"] for row in rows}

    def has_icon_seed_finished(self, project_id: str) -> bool:
        return self.get_meta(ICON_SEEDED_META_PREFIX + project_id) is not None

    def mark_icon_seed_finished(self, project_id: str) -> None:
        self.set_meta(ICON_SEEDED_META_PREFIX + project_id, "1")
