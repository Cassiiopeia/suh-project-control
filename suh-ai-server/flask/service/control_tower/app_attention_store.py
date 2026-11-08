"""앱 확인할 일 저장소 (ControlTowerStore 믹스인): 소스, 수집 상태, 항목, 항목 설정, 알림 기준, 값 이력
수집 결과 반영은 commit_attention_result 한 트랜잭션 (_connection·_write_transaction은 ControlTowerStore가 제공)"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

ATTENTION_HISTORY_RETENTION = timedelta(days=90)
ATTENTION_MISSING_ITEM_RETENTION = timedelta(days=7)  # 스냅샷에서 빠진 항목 보관 (앱 배포 실수 보호)


@dataclass(frozen=True)
class AttentionSource:
    project_id: str
    source_id: str
    url: str
    is_enabled: bool
    mode: str  # pull, push, both
    interval_seconds: int
    timeout_seconds: int
    stale_after_seconds: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AttentionSourceState:
    project_id: str
    source_id: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_result: str | None  # FETCH_RESULTS 분류
    last_error: str | None
    consecutive_failures: int
    etag: str | None
    last_generated_at: datetime | None  # 마지막으로 반영한 스냅샷 시각
    app: str | None
    app_version: str | None
    environment: str | None
    is_baseline_done: bool  # 첫 성공 반영 후 True (그 전 스냅샷은 알림 없이 기준선)
    failure_alerted_at: datetime | None  # 연동 끊김 알림을 보낸 시각 (복구 시 알림 후 None)
    next_due_at: datetime | None = None  # 앱이 poll_after_seconds로 요청한 다음 수집 시각


@dataclass(frozen=True)
class StoredAttentionItem:
    project_id: str
    source_id: str
    key: str
    kind: str
    label: str
    level: str
    group: str | None
    description: str | None
    admin_url: str | None
    latest_at: datetime | None
    detail: str | None
    count: int | None
    total: int | None
    value: float | None
    limit: float | None
    unit: str | None
    state: str | None
    raw_json: str | None
    first_seen_at: datetime
    updated_at: datetime
    missing_since: datetime | None  # 스냅샷에서 빠진 시각 (None = 현재 보고 중)


@dataclass(frozen=True)
class AttentionItemOverride:
    project_id: str
    source_id: str
    key: str
    is_hidden: bool | None = None
    label: str | None = None
    level_policy: str | None = None
    alert_rule: str | None = None
    threshold: float | None = None
    channel_kind: str | None = None
    mention_role: str | None = None  # 스펙 5.4 열 (알림 멘션 역할, 지금은 저장만)


@dataclass(frozen=True)
class AttentionItemAlertState:
    project_id: str
    source_id: str
    key: str
    last_alerted_at: datetime | None = None
    last_alerted_total: int | None = None
    last_alerted_count: int | None = None
    last_alerted_level: str | None = None
    is_threshold_exceeded: bool = False
    pending_new_count: int = 0  # new 쿨다운 중 쌓인 증가분


def new_attention_source_state(project_id: str, source_id: str) -> AttentionSourceState:
    """아직 수집한 적 없는 소스의 빈 상태"""
    return AttentionSourceState(project_id, source_id, None, None, None, None, 0, None, None, None, None, None,
                                False, None)


def _to_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _to_column(value):
    """파이썬 값 > 저장 값 (시각은 UTC ISO 문자열, bool은 0/1)"""
    if isinstance(value, datetime):
        return _to_text(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _from_row(model_class, row):
    """행 > 모델 (필드 타입 표기가 datetime / bool 이면 변환)"""
    values = {}
    for field in dataclasses.fields(model_class):
        column = row[field.name]
        if column is not None and field.type.startswith("datetime"):
            column = datetime.fromisoformat(column)
        elif column is not None and field.type.startswith("bool"):
            column = bool(column)
        values[field.name] = column
    return model_class(**values)


def _replace_row(connection, table: str, model) -> None:
    """모델 1건 저장 (키가 같으면 교체, 열 이름 = 필드 이름)"""
    names = [field.name for field in dataclasses.fields(model)]
    quoted_columns = ", ".join(f'"{name}"' for name in names)  # key, group, limit 등 예약어 대비
    placeholders = ", ".join("?" * len(names))
    connection.execute(f"INSERT OR REPLACE INTO {table} ({quoted_columns}) VALUES ({placeholders})",
                       [_to_column(getattr(model, name)) for name in names])


def _source_exists(connection, project_id: str, source_id: str) -> bool:
    return connection.execute("SELECT 1 FROM app_attention_source WHERE project_id = ? AND source_id = ?",
                              (project_id, source_id)).fetchone() is not None


def _is_history_needed(previous: StoredAttentionItem | None, current: StoredAttentionItem) -> bool:
    """새 항목이거나 count, total, value, state, level 중 하나가 바뀜"""
    if previous is None:
        return True
    return any(getattr(previous, name) != getattr(current, name)
               for name in ("count", "total", "value", "state", "level"))


class AppAttentionStoreMixin:
    # ---- 소스 ----

    def list_attention_sources(self) -> list[AttentionSource]:
        rows = self._connection().execute(
            "SELECT * FROM app_attention_source ORDER BY project_id, source_id").fetchall()
        return [_from_row(AttentionSource, row) for row in rows]

    def get_attention_source(self, project_id: str, source_id: str) -> AttentionSource | None:
        row = self._connection().execute(
            "SELECT * FROM app_attention_source WHERE project_id = ? AND source_id = ?",
            (project_id, source_id)).fetchone()
        return _from_row(AttentionSource, row) if row else None

    def save_attention_source(self, source: AttentionSource) -> None:
        """소스 저장 (있으면 설정 교체, created_at은 처음 값 유지)"""
        with self._write_transaction() as connection:
            existing = connection.execute(
                "SELECT created_at FROM app_attention_source WHERE project_id = ? AND source_id = ?",
                (source.project_id, source.source_id)).fetchone()
            if existing is not None:
                source = dataclasses.replace(source, created_at=datetime.fromisoformat(existing["created_at"]))
            _replace_row(connection, "app_attention_source", source)

    def delete_attention_source(self, project_id: str, source_id: str) -> bool:
        """소스와 같은 키의 상태, 항목, 항목 설정, 알림 기준, 이력 삭제 (한 트랜잭션) > 소스가 있었는지"""
        key_filter = "WHERE project_id = ? AND source_id = ?"
        with self._write_transaction() as connection:
            for table in ("app_attention_source_state", "app_attention_item", "app_attention_item_override",
                          "app_attention_item_alert", "app_attention_history"):
                connection.execute(f"DELETE FROM {table} {key_filter}", (project_id, source_id))
            return connection.execute(f"DELETE FROM app_attention_source {key_filter}",
                                      (project_id, source_id)).rowcount > 0

    # ---- 수집 상태·항목 조회 ----

    def get_attention_source_state(self, project_id: str, source_id: str) -> AttentionSourceState | None:
        row = self._connection().execute(
            "SELECT * FROM app_attention_source_state WHERE project_id = ? AND source_id = ?",
            (project_id, source_id)).fetchone()
        return _from_row(AttentionSourceState, row) if row else None

    def list_attention_source_states(self) -> dict[tuple[str, str], AttentionSourceState]:
        """(project_id, source_id) > 수집 상태"""
        rows = self._connection().execute("SELECT * FROM app_attention_source_state").fetchall()
        return {(row["project_id"], row["source_id"]): _from_row(AttentionSourceState, row) for row in rows}

    def load_attention_items(self, project_id: str, source_id: str) -> dict[str, StoredAttentionItem]:
        """key > 항목 (빠진 항목 포함)"""
        rows = self._connection().execute(
            'SELECT * FROM app_attention_item WHERE project_id = ? AND source_id = ? ORDER BY "key"',
            (project_id, source_id)).fetchall()
        return {row["key"]: _from_row(StoredAttentionItem, row) for row in rows}

    def load_all_attention_items(self) -> list[StoredAttentionItem]:
        """전체 소스의 항목 (빠진 항목 포함, 화면은 missing_since가 None인 것만)"""
        rows = self._connection().execute(
            'SELECT * FROM app_attention_item ORDER BY project_id, source_id, "key"').fetchall()
        return [_from_row(StoredAttentionItem, row) for row in rows]

    def load_attention_overrides(self, project_id: str, source_id: str) -> dict[str, AttentionItemOverride]:
        rows = self._connection().execute(
            "SELECT * FROM app_attention_item_override WHERE project_id = ? AND source_id = ?",
            (project_id, source_id)).fetchall()
        return {row["key"]: _from_row(AttentionItemOverride, row) for row in rows}

    def save_attention_override(self, override: AttentionItemOverride) -> None:
        with self._write_transaction() as connection:
            _replace_row(connection, "app_attention_item_override", override)

    def load_attention_alert_states(self, project_id: str, source_id: str) -> dict[str, AttentionItemAlertState]:
        rows = self._connection().execute(
            "SELECT * FROM app_attention_item_alert WHERE project_id = ? AND source_id = ?",
            (project_id, source_id)).fetchall()
        return {row["key"]: _from_row(AttentionItemAlertState, row) for row in rows}

    # ---- 수집 결과 반영 ----

    def commit_attention_result(self, project_id: str, source_id: str, state: AttentionSourceState,
                                items_to_upsert: Iterable[StoredAttentionItem], missing_keys: Iterable[str],
                                alert_states: Mapping[str, AttentionItemAlertState] | Iterable[AttentionItemAlertState],
                                now: datetime, expected_last_generated_at: datetime | None) -> bool:
        """스냅샷 1건 반영: 소스 확인 > 기준 시각 확인 > 상태 > 항목(바뀐 값만 이력) > 빠진 항목 > 알림 기준
        소스가 없거나 현재 last_generated_at이 expected와 다르면 아무것도 쓰지 않고 False"""
        alert_state_list = list(alert_states.values() if isinstance(alert_states, Mapping) else alert_states)
        with self._write_transaction() as connection:
            if not _source_exists(connection, project_id, source_id):
                return False
            current = connection.execute(
                "SELECT last_generated_at FROM app_attention_source_state WHERE project_id = ? AND source_id = ?",
                (project_id, source_id)).fetchone()
            current_text = current["last_generated_at"] if current else None
            if current_text != _to_column(expected_last_generated_at):
                return False
            _replace_row(connection, "app_attention_source_state", state)
            rows = connection.execute("SELECT * FROM app_attention_item WHERE project_id = ? AND source_id = ?",
                                      (project_id, source_id)).fetchall()
            previous_items = {row["key"]: _from_row(StoredAttentionItem, row) for row in rows}
            for item in items_to_upsert:
                previous = previous_items.get(item.key)
                stored = dataclasses.replace(
                    item, updated_at=now, missing_since=None,
                    first_seen_at=previous.first_seen_at if previous else item.first_seen_at)
                _replace_row(connection, "app_attention_item", stored)
                if _is_history_needed(previous, stored):
                    connection.execute(
                        'INSERT INTO app_attention_history (project_id, source_id, "key", observed_at, "count", total, '
                        '"value", state, level) VALUES (?,?,?,?,?,?,?,?,?)',
                        (project_id, source_id, stored.key, _to_text(now), stored.count, stored.total, stored.value,
                         stored.state, stored.level))
            for key in missing_keys:  # 이미 빠진 항목은 처음 시각 유지
                connection.execute(
                    'UPDATE app_attention_item SET missing_since = COALESCE(missing_since, ?) '
                    'WHERE project_id = ? AND source_id = ? AND "key" = ?', (_to_text(now), project_id, source_id, key))
            for alert_state in alert_state_list:
                _replace_row(connection, "app_attention_item_alert", alert_state)
            return True

    def record_attention_failure(self, project_id: str, source_id: str, state: AttentionSourceState) -> None:
        """시도 결과만 기록 (항목 유지). 이미 있는 상태 행은 시도·성공·결과·오류·실패 횟수·끊김 알림·다음 수집만 갱신해
        동시에 반영된 스냅샷 값(etag, last_generated_at 등)을 되돌리지 않음. 소스가 없으면 무시"""
        with self._write_transaction() as connection:
            if not _source_exists(connection, project_id, source_id):
                return
            attempt_columns = ("last_attempt_at", "last_success_at", "last_result", "last_error",
                               "consecutive_failures", "failure_alerted_at", "next_due_at")
            updated = connection.execute(
                f'UPDATE app_attention_source_state SET {", ".join(name + " = ?" for name in attempt_columns)} '
                "WHERE project_id = ? AND source_id = ?",
                [_to_column(getattr(state, name)) for name in attempt_columns] + [project_id, source_id])
            if updated.rowcount == 0:
                _replace_row(connection, "app_attention_source_state", state)

    # ---- 보관 정리 ----

    def purge_app_attention(self, now: datetime) -> None:
        """이력 90일, 스냅샷에서 빠진 지 7일 지난 항목(알림 기준 포함) 삭제 (항목 설정은 보존)"""
        missing_limit = _to_text(now - ATTENTION_MISSING_ITEM_RETENTION)
        with self._write_transaction() as connection:
            connection.execute("DELETE FROM app_attention_history WHERE observed_at < ?",
                               (_to_text(now - ATTENTION_HISTORY_RETENTION),))
            connection.execute(
                'DELETE FROM app_attention_item_alert WHERE ("project_id", "source_id", "key") IN '
                '(SELECT project_id, source_id, "key" FROM app_attention_item WHERE missing_since < ?)',
                (missing_limit,))
            connection.execute("DELETE FROM app_attention_item WHERE missing_since < ?", (missing_limit,))
