"""관제소 프로젝트 알림 받을 곳 저장소 (ControlTowerStore 믹스인): 추가·삭제·사용 전환·조회·발송 결과 기록
URL은 암호문만 저장 (원문 없음), _connection·_write_transaction은 ControlTowerStore가 제공"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from service.control_tower.utc_text import from_utc_text, to_utc_text

DESTINATION_COLUMNS = (
    "destination_id, project_id, kind, label, url_encrypted, encryption_scheme, url_hint, is_enabled, "
    "last_result, last_sent_at, created_at")


@dataclass(frozen=True)
class Destination:
    """받을 곳 1개 (URL 원문 없음, url_encrypted는 repr 제외)"""
    destination_id: int
    project_id: str
    kind: str
    label: str
    url_encrypted: bytes = field(repr=False)
    encryption_scheme: str
    url_hint: str
    is_enabled: bool
    last_result: str | None
    last_sent_at: datetime | None
    created_at: datetime


def _to_destination(row) -> Destination:
    return Destination(
        destination_id=row["destination_id"], project_id=row["project_id"], kind=row["kind"], label=row["label"],
        url_encrypted=bytes(row["url_encrypted"]), encryption_scheme=row["encryption_scheme"],
        url_hint=row["url_hint"], is_enabled=bool(row["is_enabled"]), last_result=row["last_result"],
        last_sent_at=from_utc_text(row["last_sent_at"]), created_at=from_utc_text(row["created_at"]))


class DestinationStoreMixin:
    def insert_destination(self, project_id: str, kind: str, label: str, url_encrypted: bytes,
                           encryption_scheme: str, url_hint: str, now: datetime, is_enabled: bool = True) -> int:
        """받을 곳 1개 추가 > 새 destination_id"""
        with self._write_transaction() as connection:
            return connection.execute(
                "INSERT INTO project_event_destination (project_id, kind, label, url_encrypted, encryption_scheme, "
                "url_hint, is_enabled, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (project_id, kind, label, url_encrypted, encryption_scheme, url_hint, int(is_enabled),
                 to_utc_text(now))).lastrowid

    def delete_destination(self, destination_id: int) -> bool:
        """받을 곳 1개 삭제 > 지운 행이 있었는지"""
        with self._write_transaction() as connection:
            return connection.execute(
                "DELETE FROM project_event_destination WHERE destination_id = ?", (destination_id,)).rowcount > 0

    def set_destination_enabled(self, destination_id: int, is_enabled: bool) -> bool:
        """사용·중지 전환 > 대상 행이 있었는지"""
        with self._write_transaction() as connection:
            return connection.execute(
                "UPDATE project_event_destination SET is_enabled = ? WHERE destination_id = ?",
                (int(is_enabled), destination_id)).rowcount > 0

    def list_destinations(self, project_id: str | None = None) -> list[Destination]:
        """받을 곳 목록 (project_id 없으면 전체), 프로젝트 > 추가 순"""
        query = f"SELECT {DESTINATION_COLUMNS} FROM project_event_destination"
        parameters: tuple = ()
        if project_id is not None:
            query += " WHERE project_id = ?"
            parameters = (project_id,)
        rows = self._connection().execute(query + " ORDER BY project_id, destination_id", parameters).fetchall()
        return [_to_destination(row) for row in rows]

    def find_destination(self, destination_id: int) -> Destination | None:
        """받을 곳 1개 조회 (없으면 None)"""
        row = self._connection().execute(
            f"SELECT {DESTINATION_COLUMNS} FROM project_event_destination WHERE destination_id = ?",
            (destination_id,)).fetchone()
        return _to_destination(row) if row is not None else None

    def list_enabled_destinations(self, project_id: str, kind: str) -> list[Destination]:
        """(프로젝트, 채널 종류)의 사용 중 받을 곳, 추가 순"""
        rows = self._connection().execute(
            f"SELECT {DESTINATION_COLUMNS} FROM project_event_destination "
            "WHERE project_id = ? AND kind = ? AND is_enabled = 1 ORDER BY destination_id",
            (project_id, kind)).fetchall()
        return [_to_destination(row) for row in rows]

    def record_destination_result(self, destination_id: int, result: str, now: datetime) -> None:
        """마지막 발송 결과 코드·시각 기록 (그 사이 삭제됐으면 무시)"""
        with self._write_transaction() as connection:
            connection.execute(
                "UPDATE project_event_destination SET last_result = ?, last_sent_at = ? WHERE destination_id = ?",
                (result, to_utc_text(now), destination_id))
