"""관제소 프로젝트 이벤트 토큰 저장소 (ControlTowerStore 믹스인): 해시 교체·삭제·상태 조회 (원문 저장 안 함)
_connection·_write_transaction은 ControlTowerStore가 제공"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from service.control_tower.utc_text import from_utc_text, to_utc_text

# project_event_token.slot 값: 현재 토큰(프로젝트당 1개) / 교체된 이전 토큰(각자 만료 전까지 유효, 여러 개)
TOKEN_SLOT_CURRENT = "current"
TOKEN_SLOT_PREVIOUS = "previous"


@dataclass(frozen=True)
class ProjectTokenState:
    """프로젝트 1개의 토큰 상태: DB 관리 여부, 현재 발급 시각, 이전 토큰별 만료 시각, (해시, 만료 시각) 후보"""
    is_db_managed: bool
    current_created_at: datetime | None
    previous_expiry_times: tuple[datetime, ...]
    token_hashes: tuple[tuple[str, datetime | None], ...]

    @classmethod
    def not_managed(cls) -> ProjectTokenState:
        """발급 이력 없음 = 환경변수 토큰 경로"""
        return cls(is_db_managed=False, current_created_at=None, previous_expiry_times=(), token_hashes=())


class ProjectTokenStoreMixin:
    def rotate_project_token(self, project_id: str, token_hash: str, now: datetime,
                             previous_expires_at: datetime, max_previous_count: int) -> None:
        """한 트랜잭션: 만료된 이전 삭제 > 현재 > 이전(만료 지정) > 상한 초과분 삭제 > 새 현재 저장 > DB 관리 표시 보장"""
        with self._write_transaction() as connection:
            # 고정 형식 UTC 문자열이라 문자열 비교 = 시각 비교
            connection.execute(
                "DELETE FROM project_event_token WHERE project_id = ? AND slot = ? AND expires_at <= ?",
                (project_id, TOKEN_SLOT_PREVIOUS, to_utc_text(now)))
            connection.execute(
                "UPDATE project_event_token SET slot = ?, expires_at = ? WHERE project_id = ? AND slot = ?",
                (TOKEN_SLOT_PREVIOUS, to_utc_text(previous_expires_at), project_id, TOKEN_SLOT_CURRENT))
            # 상한 초과분: 만료가 늦은 순으로 상한 개수만 남김 (같은 만료면 먼저 교체된 것부터 삭제)
            connection.execute(
                "DELETE FROM project_event_token WHERE token_id IN ("
                "SELECT token_id FROM project_event_token WHERE project_id = ? AND slot = ? "
                "ORDER BY expires_at DESC, token_id DESC LIMIT -1 OFFSET ?)",
                (project_id, TOKEN_SLOT_PREVIOUS, max_previous_count))
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
        current_row = next((row for row in token_rows if row["slot"] == TOKEN_SLOT_CURRENT), None)
        previous_expiry_times = tuple(from_utc_text(row["expires_at"]) for row in token_rows
                                      if row["slot"] == TOKEN_SLOT_PREVIOUS)
        return ProjectTokenState(
            is_db_managed=policy_row is not None,
            current_created_at=from_utc_text(current_row["created_at"]) if current_row else None,
            previous_expiry_times=previous_expiry_times,
            token_hashes=tuple((row["token_hash"], from_utc_text(row["expires_at"])) for row in token_rows))
