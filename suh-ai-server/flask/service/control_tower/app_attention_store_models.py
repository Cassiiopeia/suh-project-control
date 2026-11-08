"""앱 확인할 일 저장 모델: 소스, 수집 상태, 항목, 항목 설정, 알림 기준 (저장소·평가·화면 공통)"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    last_alerted_state: str | None = None  # state 규칙 비교 기준 (없으면 이전 저장 항목 값)


def new_attention_source_state(project_id: str, source_id: str) -> AttentionSourceState:
    """아직 수집한 적 없는 소스의 빈 상태"""
    return AttentionSourceState(project_id, source_id, None, None, None, None, 0, None, None, None, None, None,
                                False, None)
