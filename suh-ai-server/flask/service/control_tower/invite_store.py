"""관제소 프로젝트 초대 저장소 (ControlTowerStore 믹스인): 프로젝트별 초대 1건 조회·교체·사용 횟수 기록
_connection은 ControlTowerStore가 제공"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# 초대 링크 주소 형식: https://discord.gg/{code}
INVITE_URL_PREFIX = "https://discord.gg/"


@dataclass(frozen=True)
class ProjectInvite:
    project_id: str
    invite_code: str
    channel_id: str  # 초대가 가리키는 프로젝트 status 채널
    uses_seen: int  # 마지막 귀속 처리 때 디스코드 사용 횟수
    created_at: datetime

    @property
    def url(self) -> str:
        return INVITE_URL_PREFIX + self.invite_code


def _row_to_invite(row) -> ProjectInvite:
    return ProjectInvite(row["project_id"], row["invite_code"], row["channel_id"], row["uses_seen"],
                         datetime.fromisoformat(row["created_at"]))


class InviteStoreMixin:
    def get_project_invite(self, project_id: str) -> ProjectInvite | None:
        row = self._connection().execute(
            "SELECT * FROM project_invite WHERE project_id = ?", (project_id,)).fetchone()
        return _row_to_invite(row) if row else None

    def all_project_invites(self) -> dict[str, ProjectInvite]:
        """프로젝트 id > 초대"""
        rows = self._connection().execute("SELECT * FROM project_invite").fetchall()
        return {row["project_id"]: _row_to_invite(row) for row in rows}

    def save_project_invite(self, project_id: str, invite_code: str, channel_id: str, now: datetime) -> ProjectInvite:
        """프로젝트 초대 교체 (사용 횟수 0부터)"""
        created_text = now.astimezone(timezone.utc).isoformat(timespec="microseconds")
        with self._connection() as connection:
            connection.execute("INSERT OR REPLACE INTO project_invite VALUES (?,?,?,?,?)",
                               (project_id, invite_code, channel_id, 0, created_text))
        return self.get_project_invite(project_id)

    def update_invite_uses_seen(self, project_id: str, invite_code: str, uses_seen: int) -> None:
        """사용 횟수 기록 (그 사이 다시 만든 초대면 무시)"""
        with self._connection() as connection:
            connection.execute("UPDATE project_invite SET uses_seen = ? WHERE project_id = ? AND invite_code = ?",
                               (uses_seen, project_id, invite_code))
