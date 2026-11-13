"""관제소 프로젝트 이벤트 토큰 저장소 (ControlTowerStore 믹스인): 해시 교체·삭제·상태 조회 (원문 저장 안 함)
_connection·_write_transaction은 ControlTowerStore가 제공"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from service.control_tower.utc_text import from_utc_text, to_utc_text

# project_event_token.slot 값: 현재 토큰 / 교체 직전 토큰 (만료 전까지 유효)
TOKEN_SLOT_CURRENT = "current"
TOKEN_SLOT_PREVIOUS = "previous"


@dataclass(frozen=True)
class ProjectTokenState:
    """프로젝트 1개의 토큰 상태: DB 관리 여부, 현재 발급 시각, 이전 만료 시각, (해시, 만료 시각) 후보"""
    is_db_managed: bool
    current_created_at: datetime | None
    previous_expires_at: datetime | None
    token_hashes: tuple[tuple[str, datetime | None], ...]

    @classmethod
    def not_managed(cls) -> ProjectTokenState:
        """발급 이력 없음 = 환경변수 토큰 경로"""
        return cls(is_db_managed=False, current_created_at=None, previous_expires_at=None, token_hashes=())


class ProjectTokenStoreMixin:
    def rotate_project_token(self, project_id: str, token_hash: str, now: datetime,
                             previous_expires_at: datetime) -> None:
        """한 트랜잭션: 기존 이전 삭제 > 현재 > 이전(만료 지정) > 새 현재 저장 > DB 관리 표시 보장"""
        with self._write_transaction() as connection:
            connection.execute("DELETE FROM project_event_token WHERE project_id = ? AND slot = ?",
                               (project_id, TOKEN_SLOT_PREVIOUS))
            connection.execute(
                "UPDATE project_event_token SET slot = ?, expires_at = ? WHERE project_id = ? AND slot = ?",
                (TOKEN_SLOT_PREVIOUS, to_utc_text(previous_expires_at), project_id, TOKEN_SLOT_CURRENT))
            connection.execute(
                "INSERT INTO project_event_token (project_id, slot, token_hash, created_at, expires_at) "
                "VALUES (?,?,?,?,NULL)", (project_id, TOKEN_SLOT_CURRENT, token_hash, to_utc_text(now)))
            connection.execute(
                "INSERT OR IGNORE INTO project_event_token_policy (project_id, managed_since) VALUES (?,?)",
                (project_id, to_utc_text(now)))

    def delete_project_tokens(self, project_id: str) -> bool:
        """토큰 행만 삭제 (DB 관리 표시는 유지) > 지운 행이 있었는지"""
        with self._write_transaction() as connection:
            deleted = connection.execute(
                "DELETE FROM project_event_token WHERE project_id = ?", (project_id,)).rowcount
            return deleted > 0

    def load_project_token_state(self, project_id: str) -> ProjectTokenState:
        connection = self._connection()
        policy_row = connection.execute(
            "SELECT 1 FROM project_event_token_policy WHERE project_id = ?", (project_id,)).fetchone()
        token_rows = connection.execute(
            "SELECT slot, token_hash, created_at, expires_at FROM project_event_token WHERE project_id = ?",
            (project_id,)).fetchall()
        row_by_slot = {row["slot"]: row for row in token_rows}
        current_row = row_by_slot.get(TOKEN_SLOT_CURRENT)
        previous_row = row_by_slot.get(TOKEN_SLOT_PREVIOUS)
        return ProjectTokenState(
            is_db_managed=policy_row is not None,
            current_created_at=from_utc_text(current_row["created_at"]) if current_row else None,
            previous_expires_at=from_utc_text(previous_row["expires_at"]) if previous_row else None,
            token_hashes=tuple((row["token_hash"], from_utc_text(row["expires_at"])) for row in token_rows))
