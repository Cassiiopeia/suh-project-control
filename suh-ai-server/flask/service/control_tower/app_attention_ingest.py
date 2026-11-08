"""앱 확인할 일 단일 처리 경로 (pull·push 공통): 수집 결과 > 검증 > 늦은 스냅샷 버림 > 평가 > 저장 > 발송 > 실패분 되돌림
소스별 잠금 + 저장소 기준 시각 확인으로 동시 처리 시 최신 값 보호. 연결 확인(preview)은 저장·발송 없음"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Callable

from service.control_tower.alert_planner import Notification
from service.control_tower.app_attention_fetch import (
    FETCH_RESULT_INVALID, FETCH_RESULT_NOT_MODIFIED, FETCH_RESULT_OK, FetchOutcome,
)
from service.control_tower.app_attention_messages import (
    ItemNotification, build_item_notifications, build_source_health_notification,
)
from service.control_tower.app_attention_models import (
    INTERVAL_SECONDS_MAX, INTERVAL_SECONDS_MIN, AttentionItem, AttentionSnapshot,
)
from service.control_tower.app_attention_rules import (
    SOURCE_HEALTH_DISCONNECTED, evaluate_item_alerts, evaluate_source_health,
    resolve_effective_item,
)
from service.control_tower.app_attention_store import (
    AttentionSource, AttentionSourceState, StoredAttentionItem, new_attention_source_state,
)
from service.control_tower.app_attention_validation import parse_attention_snapshot

logger = logging.getLogger(__name__)

# ingest 결과: FETCH_RESULTS + stale(이미 반영한 시각 이하 스냅샷 버림) + conflict(동시 반영에 밀려 버림)
INGEST_RESULT_STALE = "stale"
INGEST_RESULT_CONFLICT = "conflict"
DEDUPE_HASH_LENGTH = 12
# 알림을 보내는 앱 환경 (그 외 환경은 저장만)
PRODUCTION_ENVIRONMENT = "production"
# generated_at 허용 미래 오차 (넘으면 invalid: 미래 시각 1건이 이후 스냅샷을 전부 stale로 막지 않게)
GENERATED_AT_FUTURE_TOLERANCE = timedelta(minutes=5)
ERROR_LABEL_FUTURE_GENERATED_AT = "future_generated_at"


@dataclass(frozen=True)
class IngestReport:
    result: str
    dropped_items: tuple[tuple[str, str], ...]  # (key 또는 #index, 사유)
    notification_count: int  # 발송 시도한 알림 수 (항목 알림 + 연동 끊김·복구)


class AppAttentionIngest:
    """수집 결과 처리기: 결과 분류별 상태 기록, 스냅샷 반영, 항목 알림·연동 판정 발송"""

    def __init__(self, store, dispatcher, registry_provider: Callable, is_project_down: Callable[[str], bool]):
        self._store = store
        self._dispatcher = dispatcher
        self._registry_provider = registry_provider
        self._is_project_down = is_project_down
        self._locks_guard = threading.Lock()
        self._locks_by_source: dict[tuple[str, str], threading.Lock] = {}

    def ingest(self, source: AttentionSource, outcome: FetchOutcome, now: datetime) -> IngestReport:
        """처리 1회: 소스 잠금 > 실패·not_modified는 상태만 > 검증 > 늦은 스냅샷 버림 > 평가·반영 > 발송"""
        with self._lock_for(source):
            state = self._read_state(source)
            if outcome.result == FETCH_RESULT_NOT_MODIFIED:
                return self._record_attempt(source, _succeeded_state(state, now, FETCH_RESULT_NOT_MODIFIED), now)
            if outcome.result != FETCH_RESULT_OK:
                failed_state = _failed_state(state, now, outcome.result, outcome.error_label)
                return self._record_attempt(source, failed_state, now)

            validation = parse_attention_snapshot(outcome.document)
            if validation.snapshot is None:
                failed_state = _failed_state(state, now, FETCH_RESULT_INVALID, validation.errors[0])
                return self._record_attempt(source, failed_state, now)
            snapshot = validation.snapshot
            if snapshot.generated_at > now + GENERATED_AT_FUTURE_TOLERANCE:
                failed_state = _failed_state(state, now, FETCH_RESULT_INVALID, ERROR_LABEL_FUTURE_GENERATED_AT)
                return self._record_attempt(source, failed_state, now)
            if state.last_generated_at is not None and snapshot.generated_at <= state.last_generated_at:
                # 늦게 온 스냅샷: 값은 버리고 연락 성공만 기록 (같은 스냅샷 반복 응답도 끊김으로 안 보이게)
                attempt = self._record_attempt(source, _succeeded_state(state, now, FETCH_RESULT_OK), now)
                return IngestReport(INGEST_RESULT_STALE, validation.dropped_items, attempt.notification_count)
            return self._apply_snapshot(source, state, snapshot, outcome.etag, validation.dropped_items, now)

    def check_source_health(self, source: AttentionSource, now: datetime) -> None:
        """연동 끊김·복구만 판정 (push 전용 소스용, 폴러가 매 틱 호출)"""
        with self._lock_for(source):
            state = self._read_state(source)
            next_state, health_notification = self._apply_source_health(source, state, now)
            if health_notification is None:
                return
            self._store.record_attention_failure(source.project_id, source.source_id, next_state)
            self._dispatch_source_health(source, health_notification, state.failure_alerted_at)

    def preview(self, source: AttentionSource, outcome: FetchOutcome) -> dict:
        """연결 확인용 요약 (저장·발송 없음): 결과, 사유, 최상위 오류, 버린 항목, 항목 요약"""
        if outcome.result != FETCH_RESULT_OK:
            return _preview_body(outcome.result, outcome.error_label, (), (), ())
        validation = parse_attention_snapshot(outcome.document)
        if validation.snapshot is None:
            return _preview_body(FETCH_RESULT_INVALID, validation.errors[0], validation.errors,
                                 validation.dropped_items, ())
        return _preview_body(FETCH_RESULT_OK, None, (), validation.dropped_items, validation.snapshot.items)

    # ---- 단계 ----

    def _apply_snapshot(self, source: AttentionSource, state: AttentionSourceState, snapshot: AttentionSnapshot,
                        etag: str | None, dropped_items: tuple, now: datetime) -> IngestReport:
        """스냅샷 반영: 유효 항목 > 알림 평가 > 새 상태(연동 판정 포함) > 기준 시각 확인 저장 > 발송"""
        project_id, source_id = source.project_id, source.source_id
        overrides = self._store.load_attention_overrides(project_id, source_id)
        previous_items = self._store.load_attention_items(project_id, source_id)
        effective_items = [resolve_effective_item(item, overrides.get(item.key)) for item in snapshot.items]
        evaluation = evaluate_item_alerts(
            effective_items, previous_items, self._store.load_attention_alert_states(project_id, source_id),
            is_baseline=not state.is_baseline_done,
            is_production=snapshot.environment == PRODUCTION_ENVIRONMENT, now=now)
        next_alert_states = _with_source_keys(evaluation.next_states, project_id, source_id)

        next_state = replace(
            _succeeded_state(state, now, FETCH_RESULT_OK), etag=etag, last_generated_at=snapshot.generated_at,
            app=snapshot.app, app_version=snapshot.app_version, environment=snapshot.environment,
            is_baseline_done=True, next_due_at=_next_due_at(source, snapshot, now))
        next_state, health_notification = self._apply_source_health(source, next_state, now)

        reported_keys = {item.key for item in snapshot.items}
        missing_keys = [key for key in previous_items if key not in reported_keys]
        stored_items = [_to_stored_item(project_id, source_id, item, now) for item in snapshot.items]
        is_committed = self._store.commit_attention_result(
            project_id, source_id, next_state, stored_items, missing_keys, next_alert_states, now,
            expected_last_generated_at=state.last_generated_at)
        if not is_committed:
            logger.info("[control-tower app-attention] snapshot dropped : %s.%s : concurrent commit",
                        project_id, source_id)
            return IngestReport(INGEST_RESULT_CONFLICT, dropped_items, 0)

        # 저장 먼저 > 발송 > 못 보낸 것만 되돌림 (소스 잠금 안 + 저장 전 발송 없음 > 같은 알림 중복 발송 없음)
        item_notifications = build_item_notifications(project_id, self._project_name(project_id), source_id,
                                                      evaluation.lines, _dedupe_suffix(snapshot.generated_at))
        self._dispatch_item_notifications(source, item_notifications, evaluation.undelivered_states)
        if health_notification is not None:
            self._dispatch_source_health(source, health_notification, state.failure_alerted_at)
        notification_count = len(item_notifications) + (1 if health_notification is not None else 0)
        return IngestReport(FETCH_RESULT_OK, dropped_items, notification_count)

    def _record_attempt(self, source: AttentionSource, state: AttentionSourceState, now: datetime) -> IngestReport:
        """항목은 그대로 두고 시도 결과·연동 판정만 기록 > 판정 알림 발송"""
        next_state, health_notification = self._apply_source_health(source, state, now)
        self._store.record_attention_failure(source.project_id, source.source_id, next_state)
        notification_count = 0
        if health_notification is not None:
            self._dispatch_source_health(source, health_notification, state.failure_alerted_at)
            notification_count = 1
        return IngestReport(next_state.last_result or "", (), notification_count)

    def _dispatch_item_notifications(self, source: AttentionSource, item_notifications: list[ItemNotification],
                                     undelivered_states: dict) -> None:
        """항목 알림 발송 > 한 건도 못 보낸 key만 처리 전 기준으로 저장 (전역 긴급만 실패한 key는 이미 보냄)"""
        delivered_keys: set[str] = set()
        failed_keys: set[str] = set()
        for item_notification in item_notifications:
            is_delivered = self._dispatch_safely(item_notification.notification)
            (delivered_keys if is_delivered else failed_keys).update(item_notification.keys)
        undelivered_keys = sorted(failed_keys - delivered_keys)
        if not undelivered_keys or not self._is_retry_meaningful():
            return
        held_states = _with_source_keys({key: undelivered_states[key] for key in undelivered_keys},
                                        source.project_id, source.source_id)
        self._store.save_attention_alert_states(source.project_id, source.source_id, held_states.values())
        logger.warning("[control-tower app-attention] alert kept for retry : %s.%s : %d items",
                       source.project_id, source.source_id, len(undelivered_keys))

    def _dispatch_source_health(self, source: AttentionSource, notification: Notification,
                                previous_failure_alerted_at: datetime | None) -> None:
        """연동 끊김·복구 발송 > 못 보내면 끊김 알림 시각을 처리 전 값으로 (다음 처리에서 재판정)"""
        if self._dispatch_safely(notification) or not self._is_retry_meaningful():
            return
        self._store.save_attention_failure_alerted_at(source.project_id, source.source_id,
                                                      previous_failure_alerted_at)
        logger.warning("[control-tower app-attention] source health kept for retry : %s.%s",
                       source.project_id, source.source_id)

    def _is_retry_meaningful(self) -> bool:
        """디스코드 미설정이면 재시도 안 함 (설정 전까지 매 처리 재발송·누적 방지)"""
        return self._dispatcher.is_delivery_configured()

    def _apply_source_health(self, source: AttentionSource, state: AttentionSourceState,
                             now: datetime) -> tuple[AttentionSourceState, Notification | None]:
        """연동 판정 > 끊김이면 failure_alerted_at = now, 복구면 None + 알림 1건"""
        verdict = evaluate_source_health(source, state, self._is_project_down(source.project_id), now)
        if verdict is None:
            return state, None
        failure_alerted_at = now if verdict == SOURCE_HEALTH_DISCONNECTED else None
        reason = (state.last_error or state.last_result) if verdict == SOURCE_HEALTH_DISCONNECTED else None
        notification = build_source_health_notification(
            source.project_id, self._project_name(source.project_id), source.source_id, verdict, reason)
        logger.info("[control-tower app-attention] source %s : %s.%s", verdict, source.project_id, source.source_id)
        return replace(state, failure_alerted_at=failure_alerted_at), notification

    def _read_state(self, source: AttentionSource) -> AttentionSourceState:
        state = self._store.get_attention_source_state(source.project_id, source.source_id)
        return state or new_attention_source_state(source.project_id, source.source_id)

    def _lock_for(self, source: AttentionSource) -> threading.Lock:
        """(project_id, source_id)별 잠금 (pull 스레드와 push 요청 스레드 직렬화)"""
        with self._locks_guard:
            return self._locks_by_source.setdefault((source.project_id, source.source_id), threading.Lock())

    def _project_name(self, project_id: str) -> str:
        for project in self._registry_provider().projects:
            if project.id == project_id:
                return project.name
        return project_id

    def _dispatch_safely(self, notification: Notification) -> bool:
        """발송 1건 > 전달 여부 (실패·예외는 로그 후 False)"""
        try:
            if self._dispatcher.dispatch(notification) is True:
                return True
            logger.warning("[control-tower app-attention] dispatch not delivered : kind %s", notification.kind)
        except Exception as error:
            logger.warning("[control-tower app-attention] dispatch failed : kind %s : %s",
                           notification.kind, type(error).__name__)
        return False


def _succeeded_state(state: AttentionSourceState, now: datetime, result: str) -> AttentionSourceState:
    """연락 성공: 시도·성공 시각 갱신, 실패 횟수 0 (항목·스냅샷 값 유지)"""
    return replace(state, last_attempt_at=now, last_success_at=now, last_result=result, last_error=None,
                   consecutive_failures=0)


def _failed_state(state: AttentionSourceState, now: datetime, result: str,
                  error_label: str | None) -> AttentionSourceState:
    """수집 실패: 시도 시각·결과·사유 기록, 실패 횟수 +1 (마지막 성공·항목 유지)"""
    return replace(state, last_attempt_at=now, last_result=result, last_error=error_label,
                   consecutive_failures=state.consecutive_failures + 1)


def _with_source_keys(alert_states: dict, project_id: str, source_id: str) -> dict:
    """알림 기준에 소스 키 채움 (처음 보는 key의 기준은 소스 키가 비어 있음)"""
    return {key: replace(alert_state, project_id=project_id, source_id=source_id)
            for key, alert_state in alert_states.items()}


def _next_due_at(source: AttentionSource, snapshot: AttentionSnapshot, now: datetime) -> datetime | None:
    """앱 요청 poll_after_seconds([60, 3600]로 자름)와 interval 중 큰 값 > 다음 수집 시각 (요청 없으면 None)"""
    if snapshot.poll_after_seconds is None:
        return None
    poll_after_seconds = min(max(snapshot.poll_after_seconds, INTERVAL_SECONDS_MIN), INTERVAL_SECONDS_MAX)
    return now + timedelta(seconds=max(poll_after_seconds, source.interval_seconds))


def _to_stored_item(project_id: str, source_id: str, item: AttentionItem, now: datetime) -> StoredAttentionItem:
    """검증된 항목 > 저장 항목 (원본은 raw_json, first_seen_at은 저장소가 기존 값 유지)"""
    raw_json = json.dumps(item.raw, ensure_ascii=False) if item.raw is not None else None
    return StoredAttentionItem(
        project_id, source_id, item.key, item.kind, item.label, item.level, item.group, item.description,
        item.admin_url, item.latest_at, item.detail, item.count, item.total, item.value, item.limit, item.unit,
        item.state, raw_json, first_seen_at=now, updated_at=now, missing_since=None)


def _dedupe_suffix(generated_at: datetime) -> str:
    """스냅샷 시각 > 짧은 해시 (같은 스냅샷 알림 중복 키)"""
    return hashlib.sha256(generated_at.isoformat().encode("utf-8")).hexdigest()[:DEDUPE_HASH_LENGTH]


def _summarize_value(item: AttentionItem) -> str | None:
    """항목 값 요약: count '3건 (전체 10)', gauge '85 / 100 %', state 'degraded', 그 외 None"""
    if item.kind == "count" and item.count is not None:
        text = f"{item.count}{item.unit or '건'}"
        return text + (f" (전체 {item.total})" if item.total is not None else "")
    if item.kind == "gauge" and item.value is not None:
        text = f"{item.value:g}" + (f" / {item.limit:g}" if item.limit is not None else "")
        return text + (f" {item.unit}" if item.unit else "")
    return item.state


def _preview_body(result: str, error_label: str | None, errors: tuple, dropped_items: tuple,
                  items: tuple[AttentionItem, ...]) -> dict:
    return {
        "result": result,
        "error_label": error_label,
        "errors": list(errors),
        "dropped_items": [{"key": key, "reason": reason} for key, reason in dropped_items],
        "items": [{"key": item.key, "label": item.label, "kind": item.kind, "level": item.level,
                   "summary": _summarize_value(item)} for item in items],
    }
