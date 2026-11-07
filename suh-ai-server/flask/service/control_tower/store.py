"""관제소 저장소: 점검 결과·일별 집계·장애·서비스 상태·이벤트 중복·바인딩·점검 창·메타 (+ 덮어쓰기·초대 믹스인)
스레드마다 SQLite 연결(WAL), 시각은 UTC ISO 문자열 저장 > aware datetime 복원"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from service.control_tower.check_runner import CheckResult
from service.control_tower.invite_store import InviteStoreMixin
from service.control_tower.override_store import OverrideStoreMixin
from service.control_tower.registry import MaintenanceWindow
from service.control_tower.state_machine import Observation, ServiceState
from service.control_tower.store_schema import SCHEMA_STATEMENTS, apply_column_migrations
from service.control_tower.time_zones import KST

CONNECTION_TIMEOUT_SECONDS = 10  # 쓰기 잠금 대기
BUSY_TIMEOUT_MILLISECONDS = 10000
EVENT_DEDUPE_WINDOW = timedelta(minutes=10)
CHECK_RESULT_RETENTION = timedelta(days=7)
EVENT_LOG_RETENTION = timedelta(days=30)
LONG_TERM_RETENTION = timedelta(days=400)  # 일별 집계, 종료된 장애


def _to_text(moment: datetime) -> str:
    """aware datetime > UTC ISO 문자열 (고정 형식이라 문자열 비교 = 시각 비교)"""
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _from_text(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _kst_day(moment: datetime) -> str:
    return moment.astimezone(KST).strftime("%Y-%m-%d")


def _checks_of(observation: Observation) -> list[CheckResult]:
    """집계에 쓰는 유효 점검 (외부는 워커 결과 수신 시에만)"""
    checks = []
    if observation.internal is not None:
        checks.append(observation.internal)
    if observation.external is not None and observation.is_external_known:
        checks.append(observation.external)
    return checks


def _check_columns(check: CheckResult | None) -> tuple:
    if check is None:
        return (None, None, None, None, None)
    return (int(check.is_ok), int(check.is_slow), check.status_code, check.latency_milliseconds, check.error)


class ControlTowerStore(OverrideStoreMixin, InviteStoreMixin):
    def __init__(self, path: str):
        self._path = path
        self._thread_local = threading.local()
        self._opened_connections: list[sqlite3.Connection] = []  # close()에서 전부 닫기 위한 추적
        self._opened_connections_lock = threading.Lock()

    def _connection(self) -> sqlite3.Connection:
        """현재 스레드 전용 연결 (없으면 생성)"""
        connection = getattr(self._thread_local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self._path, timeout=CONNECTION_TIMEOUT_SECONDS, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MILLISECONDS}")
            self._thread_local.connection = connection
            with self._opened_connections_lock:
                self._opened_connections.append(connection)
        return connection

    def close(self) -> None:
        """모든 스레드의 연결 닫기 (이후 호출 시 연결을 새로 엶)"""
        with self._opened_connections_lock:
            for connection in self._opened_connections:
                connection.close()
            self._opened_connections.clear()
            self._thread_local = threading.local()

    @contextmanager
    def _write_transaction(self):
        """쓰기 잠금을 먼저 잡는 트랜잭션: 조회 > 기록 사이 경합 방지 (성공 시 커밋, 예외 시 롤백)"""
        connection = self._connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        connection.commit()

    def initialize(self) -> None:
        """상위 폴더 생성 > 테이블·인덱스 생성 > 기존 DB 열 추가"""
        parent_directory = os.path.dirname(self._path)
        if parent_directory:
            os.makedirs(parent_directory, exist_ok=True)
        with self._connection() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            apply_column_migrations(connection)

    # ---- 점검 결과·일별 집계 ----

    def save_results(self, service_id: str, observation: Observation, now: datetime) -> None:
        """원시 결과 저장 + 일별 집계 UPSERT (데이터 없는 틱은 저장·집계 안 함)"""
        checks = _checks_of(observation)
        if not checks:
            return
        is_tick_ok = all(check.is_ok for check in checks)  # 상태 기계와 같은 실패 틱 규칙
        external_check = observation.external if observation.is_external_known else None
        with self._connection() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO check_result VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (service_id, _to_text(now), int(observation.is_external_known),
                 *_check_columns(observation.internal), *_check_columns(external_check)),
            )
            if inserted.rowcount == 0:  # 같은 시각 재저장은 집계 중복 방지
                return
            connection.execute(
                "INSERT INTO daily_rollup (day, service_id, total, ok) VALUES (?,?,1,?) "
                "ON CONFLICT(day, service_id) DO UPDATE SET total = total + 1, ok = ok + excluded.ok",
                (_kst_day(now), service_id, int(is_tick_ok)),
            )

    def uptime_by_day(self, service_id: str, days: int) -> list[tuple[str, int, int]]:
        """최근 N개 KST 일자의 (day, total, ok), 오래된 순"""
        rows = self._connection().execute(
            "SELECT day, total, ok FROM daily_rollup WHERE service_id = ? ORDER BY day DESC LIMIT ?",
            (service_id, days),
        ).fetchall()
        return [(row["day"], row["total"], row["ok"]) for row in reversed(rows)]

    def rollups_on_day(self, day: str) -> dict[str, tuple[int, int]]:
        """KST 일자(YYYY-MM-DD) 1개의 서비스별 (total, ok)"""
        rows = self._connection().execute(
            "SELECT service_id, total, ok FROM daily_rollup WHERE day = ?", (day,)).fetchall()
        return {row["service_id"]: (row["total"], row["ok"]) for row in rows}

    # ---- 서비스 상태 ----

    def load_states(self) -> dict[str, ServiceState]:
        rows = self._connection().execute("SELECT * FROM service_state").fetchall()
        return {
            row["service_id"]: ServiceState(
                row["status"], row["consecutive_failures"], row["consecutive_successes"], row["cause"],
                _from_text(row["since"]), _from_text(row["last_notified_at"]), bool(row["is_down_notified"]))
            for row in rows
        }

    def save_state(self, service_id: str, state: ServiceState) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO service_state VALUES (?,?,?,?,?,?,?,?)",
                (service_id, state.status, state.consecutive_failures, state.consecutive_successes, state.cause,
                 _to_text(state.since) if state.since else None,
                 _to_text(state.last_notified_at) if state.last_notified_at else None,
                 int(state.is_down_notified)),
            )

    # ---- 장애 구간 ----

    def open_incident(self, service_id: str, cause: str, started_at: datetime,
                      is_in_maintenance: bool = False) -> int:
        """장애 열기 (이미 열린 장애가 있으면 그 id 반환), is_in_maintenance: 여는 시점 점검 창 안"""
        with self._write_transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM incident WHERE service_id = ? AND ended_at IS NULL", (service_id,)).fetchone()
            if existing is not None:
                return existing["id"]
            return connection.execute(
                "INSERT INTO incident (service_id, cause, started_at, is_within_maintenance) VALUES (?,?,?,?)",
                (service_id, cause, _to_text(started_at), int(is_in_maintenance))).lastrowid

    def close_incident(self, service_id: str, ended_at: datetime, is_in_maintenance: bool = False) -> int | None:
        """열린 장애 닫기 (없으면 None), 점검 창 안 종료가 아니면 is_within_maintenance 0"""
        with self._write_transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM incident WHERE service_id = ? AND ended_at IS NULL", (service_id,)).fetchone()
            if existing is None:
                return None
            connection.execute(
                "UPDATE incident SET ended_at = ?, is_within_maintenance = is_within_maintenance AND ? WHERE id = ?",
                (_to_text(ended_at), int(is_in_maintenance), existing["id"]))
            return existing["id"]

    def recent_incidents(self, limit: int, since: datetime) -> list[dict]:
        """since 이후 시작했거나 진행 중인 장애, 최신순"""
        rows = self._connection().execute(
            "SELECT id, service_id, cause, started_at, ended_at, is_within_maintenance FROM incident "
            "WHERE started_at >= ? OR ended_at IS NULL ORDER BY started_at DESC, id DESC LIMIT ?",
            (_to_text(since), limit)).fetchall()
        return [{"id": row["id"], "service_id": row["service_id"], "cause": row["cause"],
                 "started_at": _from_text(row["started_at"]), "ended_at": _from_text(row["ended_at"]),
                 "is_within_maintenance": bool(row["is_within_maintenance"])}
                for row in rows]

    def recent_incidents_of_service(self, service_id: str, limit: int) -> list[dict]:
        """서비스 1개의 장애, 최신순"""
        rows = self._connection().execute(
            "SELECT id, cause, started_at, ended_at FROM incident WHERE service_id = ? "
            "ORDER BY started_at DESC, id DESC LIMIT ?", (service_id, limit)).fetchall()
        return [{"id": row["id"], "service_id": service_id, "cause": row["cause"],
                 "started_at": _from_text(row["started_at"]), "ended_at": _from_text(row["ended_at"])}
                for row in rows]

    def incidents_overlapping(self, start: datetime, end: datetime) -> list[dict]:
        """[start, end) 구간과 겹친 장애 (진행 중 포함), 시작순"""
        rows = self._connection().execute(
            "SELECT id, service_id, cause, started_at, ended_at FROM incident "
            "WHERE started_at < ? AND (ended_at IS NULL OR ended_at > ?) ORDER BY started_at, id",
            (_to_text(end), _to_text(start))).fetchall()
        return [{"id": row["id"], "service_id": row["service_id"], "cause": row["cause"],
                 "started_at": _from_text(row["started_at"]), "ended_at": _from_text(row["ended_at"])}
                for row in rows]

    # ---- 이벤트 중복 억제·조회 ----

    def recent_events(self, limit: int) -> list[dict]:
        """최근 접수 이벤트 (dedupe_key 제외), 최신순"""
        rows = self._connection().execute(
            "SELECT id, project_id, kind, created_at FROM event_log ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,)).fetchall()
        return [{"id": row["id"], "project_id": row["project_id"], "kind": row["kind"],
                 "created_at": _from_text(row["created_at"])} for row in rows]

    def record_event(self, project_id: str, kind: str, dedupe_key: str | None, created_at: datetime) -> bool:
        """이벤트 기록: 같은 (프로젝트, 키)가 10분 내 있으면 False(기록 안 함), 키 없으면 항상 True"""
        with self._write_transaction() as connection:
            if dedupe_key:
                window_start = _to_text(created_at - EVENT_DEDUPE_WINDOW)
                duplicate = connection.execute(
                    "SELECT 1 FROM event_log WHERE project_id = ? AND dedupe_key = ? AND created_at > ? LIMIT 1",
                    (project_id, dedupe_key, window_start)).fetchone()
                if duplicate is not None:
                    return False
            connection.execute(
                "INSERT INTO event_log (project_id, kind, dedupe_key, created_at) VALUES (?,?,?,?)",
                (project_id, kind, dedupe_key or None, _to_text(created_at)))
            return True

    # ---- 디스코드 바인딩·메타 ----

    def get_binding(self, scope: str, kind: str) -> str | None:
        row = self._connection().execute(
            "SELECT discord_id FROM discord_binding WHERE scope = ? AND kind = ?", (scope, kind)).fetchone()
        return row["discord_id"] if row else None

    def all_bindings(self) -> dict[tuple[str, str], str]:
        """바인딩 전체: (scope, kind) > 디스코드 id"""
        rows = self._connection().execute("SELECT scope, kind, discord_id FROM discord_binding").fetchall()
        return {(row["scope"], row["kind"]): row["discord_id"] for row in rows}

    def set_binding(self, scope: str, kind: str, discord_id: str) -> None:
        with self._connection() as connection:
            connection.execute("INSERT OR REPLACE INTO discord_binding VALUES (?,?,?)", (scope, kind, discord_id))

    def get_meta(self, key: str) -> str | None:
        row = self._connection().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    # ---- 점검 창 ----

    def set_maintenance(self, service_id: str, until: datetime, reason: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO maintenance_override VALUES (?,?,?)", (service_id, _to_text(until), reason))

    def clear_maintenance(self, service_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM maintenance_override WHERE service_id = ?", (service_id,))

    def active_maintenance(self, now: datetime) -> dict[str, MaintenanceWindow]:
        """until > now 인 점검 창만"""
        rows = self._connection().execute(
            "SELECT service_id, until, reason FROM maintenance_override WHERE until > ?", (_to_text(now),)).fetchall()
        return {row["service_id"]: MaintenanceWindow(row["service_id"], _from_text(row["until"]), row["reason"])
                for row in rows}

    # ---- 보관 정리 ----

    def purge(self, now: datetime) -> None:
        """보관 기간 초과 삭제: 점검 7일, 이벤트 30일, 일별 집계·종료 장애 400일 (진행 중 장애 보존)"""
        long_term_limit = _to_text(now - LONG_TERM_RETENTION)
        with self._connection() as connection:
            connection.execute("DELETE FROM check_result WHERE checked_at < ?", (_to_text(now - CHECK_RESULT_RETENTION),))
            connection.execute("DELETE FROM event_log WHERE created_at < ?", (_to_text(now - EVENT_LOG_RETENTION),))
            connection.execute("DELETE FROM daily_rollup WHERE day < ?", (_kst_day(now - LONG_TERM_RETENTION),))
            connection.execute("DELETE FROM incident WHERE ended_at IS NOT NULL AND ended_at < ?", (long_term_limit,))
