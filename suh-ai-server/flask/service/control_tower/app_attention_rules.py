"""앱 확인할 일 알림 평가: 유효 항목 + 이전 값·알림 기준 > 알림 줄 + 다음 알림 기준, 소스 연동 끊김·복구 판정
순수 함수 (저장·네트워크·시계 없음, now는 인자). 규칙 5종은 app_attention_effective 참고"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from service.control_tower.app_attention_effective import (  # noqa: F401  (규칙 상수 공개 위치)
    ALERT_RULE_LEVEL, ALERT_RULE_NEW, ALERT_RULE_OFF, ALERT_RULE_STATE, ALERT_RULE_THRESHOLD, ALERT_RULES,
    DEFAULT_CHANNEL_KIND, DEFAULT_RULE_BY_KIND, LEVEL_OK, LEVEL_POLICIES, EffectiveItem, level_rank,
    resolve_effective_item,
)
from service.control_tower.app_attention_store import (
    AttentionItemAlertState, AttentionSource, AttentionSourceState, StoredAttentionItem,
)

# 같은 항목 new 알림 최소 간격 (그 사이 증가분은 pending_new_count에 합산)
NEW_ALERT_COOLDOWN = timedelta(minutes=10)
# level 규칙이 알리는 최소 수준 (warning 이상으로 올라갈 때만)
LEVEL_RULE_MINIMUM = "warning"
# 수집 성공으로 보는 결과 (not_modified = 304, 값 그대로)
SUCCESS_RESULTS = ("ok", "not_modified")
SOURCE_HEALTH_DISCONNECTED = "disconnected"
SOURCE_HEALTH_RECOVERED = "recovered"
STATE_OK = "ok"
DEFAULT_COUNT_UNIT = "건"
DETAIL_SEPARATOR = " · "


@dataclass(frozen=True)
class AlertLine:
    """알림 메시지 본문 1줄 (항목 1건)"""
    key: str
    label: str
    level: str  # 줄 수준 (해소 줄은 해소 전 수준)
    admin_url: str | None
    text: str  # 한 줄 설명 (예: "+5, 지금 8건")
    channel_kind: str
    is_recovery: bool


@dataclass(frozen=True)
class ItemAlertEvaluation:
    """항목 전체 평가 결과"""
    lines: list[AlertLine]
    next_states: dict[str, AttentionItemAlertState]  # 발송 성공·줄 없음일 때 저장할 기준 (key > 기준)
    undelivered_states: dict[str, AttentionItemAlertState]  # 줄 있는 key만: 발송 실패 시 저장할 기준 (처리 전 기준 유지)


@dataclass(frozen=True)
class _Baseline:
    """항목 1건의 비교 기준 (알림 기준 우선, 없으면 이전 저장 항목)"""
    total: int | None
    count: int | None
    level: str | None
    state: str | None
    value: float | None
    is_threshold_exceeded: bool


def evaluate_item_alerts(effective_items: list[EffectiveItem], previous_items: dict[str, StoredAttentionItem],
                         alert_states: dict[str, AttentionItemAlertState], is_baseline: bool, is_production: bool,
                         now: datetime) -> ItemAlertEvaluation:
    """항목 전체 평가: 항목별 기준 > 규칙별 줄 판정 > 다음 기준·발송 실패 시 기준 (숨김·off·ok·기준선·비production도 기준은 갱신)
    기준이 전혀 없는 새 key는 이번 값을 기준으로만 저장 (알림 없음)"""
    lines: list[AlertLine] = []
    next_states: dict[str, AttentionItemAlertState] = {}
    undelivered_states: dict[str, AttentionItemAlertState] = {}
    can_alert = not is_baseline and is_production
    for effective in effective_items:
        key = effective.item.key
        alert_state = alert_states.get(key)
        baseline = _resolve_baseline(effective, previous_items.get(key), alert_state)
        if alert_state is None:
            alert_state = AttentionItemAlertState(project_id="", source_id="", key=key)
        is_alertable = can_alert and baseline is not None and not effective.is_hidden \
            and effective.rule != ALERT_RULE_OFF
        line, next_state = _evaluate_one(effective, baseline, alert_state, is_alertable, now)
        if line is not None:
            lines.append(line)
            undelivered_states[key] = _hold_undelivered_state(effective, baseline, alert_state, next_state)
        next_states[key] = next_state
    return ItemAlertEvaluation(lines, next_states, undelivered_states)


def evaluate_source_health(source: AttentionSource, state: AttentionSourceState | None, is_project_down: bool,
                           now: datetime) -> Literal["disconnected", "recovered"] | None:
    """소스 연동 판정: 방금 성공 + 끊김 알림 있음 > recovered, 마지막 성공(없으면 등록 시각)부터
    stale_after_seconds 넘김 + 끊김 알림 없음 > disconnected (프로젝트 down·소스 꺼짐이면 None)
    failure_alerted_at 갱신은 호출부 (pull·push 공통 기준)"""
    failure_alerted_at = state.failure_alerted_at if state is not None else None
    is_just_succeeded = state is not None and state.last_result in SUCCESS_RESULTS
    if is_just_succeeded and failure_alerted_at is not None:
        return SOURCE_HEALTH_RECOVERED
    if failure_alerted_at is not None or not source.is_enabled or is_project_down:
        return None
    last_success_at = state.last_success_at if state is not None else None
    since = last_success_at or source.created_at
    if now - since > timedelta(seconds=source.stale_after_seconds):
        return SOURCE_HEALTH_DISCONNECTED
    return None


def _resolve_baseline(effective: EffectiveItem, previous_item: StoredAttentionItem | None,
                      alert_state: AttentionItemAlertState | None) -> _Baseline | None:
    """비교 기준: 알림 기준 값 > 없으면 이전 저장 항목 값, 둘 다 없으면 None (새 key)"""
    if previous_item is None and alert_state is None:
        return None
    previous_value = previous_item.value if previous_item is not None else None
    if alert_state is not None:
        is_threshold_exceeded = alert_state.is_threshold_exceeded
    else:
        is_threshold_exceeded = _is_threshold_exceeded(previous_value, effective.threshold)
    return _Baseline(
        total=_first_present(alert_state.last_alerted_total if alert_state else None,
                             previous_item.total if previous_item else None),
        count=_first_present(alert_state.last_alerted_count if alert_state else None,
                             previous_item.count if previous_item else None),
        level=_first_present(alert_state.last_alerted_level if alert_state else None,
                             _previous_effective_level(effective, previous_item)),
        state=_first_present(alert_state.last_alerted_state if alert_state else None,
                             previous_item.state if previous_item else None),
        value=previous_value,
        is_threshold_exceeded=is_threshold_exceeded,
    )


def _evaluate_one(effective: EffectiveItem, baseline: _Baseline | None, alert_state: AttentionItemAlertState,
                  is_alertable: bool, now: datetime) -> tuple[AlertLine | None, AttentionItemAlertState]:
    """항목 1건: 규칙별 줄 판정 > 다음 기준 (현재 값·수준·기준 넘김 여부, new 쿨다운 누적)"""
    item = effective.item
    is_exceeded = _is_threshold_exceeded(item.value, effective.threshold)
    next_state = replace(alert_state, last_alerted_total=item.total, last_alerted_count=item.count,
                         last_alerted_level=effective.level, last_alerted_state=item.state,
                         is_threshold_exceeded=is_exceeded, pending_new_count=0)
    if not is_alertable:
        return None, next_state

    # 규칙별 줄 (new는 쿨다운 상태를 함께 갱신)
    if effective.rule == ALERT_RULE_NEW:
        return _evaluate_new(effective, baseline, alert_state, next_state, now)
    line = None
    if effective.rule == ALERT_RULE_THRESHOLD:
        line = _evaluate_threshold(effective, baseline, is_exceeded)
    elif effective.rule == ALERT_RULE_STATE:
        line = _evaluate_state(effective, baseline)
    elif effective.rule == ALERT_RULE_LEVEL:
        line = _evaluate_level(effective, baseline)
    if line is not None and line.level == LEVEL_OK:
        line = None
    if line is not None:
        next_state = replace(next_state, last_alerted_at=now)
    return line, next_state


def _evaluate_new(effective: EffectiveItem, baseline: _Baseline, alert_state: AttentionItemAlertState,
                  next_state: AttentionItemAlertState,
                  now: datetime) -> tuple[AlertLine | None, AttentionItemAlertState]:
    """new: 증가분(total 둘 다 있으면 total 차이, 아니면 count 차이) > 쿨다운 안이면 누적, 지나면 누적+증가분 1줄"""
    item = effective.item
    pending_count = alert_state.pending_new_count + _new_increase(effective, baseline)
    is_in_cooldown = alert_state.last_alerted_at is not None \
        and now - alert_state.last_alerted_at < NEW_ALERT_COOLDOWN
    # 유효 수준 ok: 줄 없음, 누적도 버림
    if effective.level == LEVEL_OK or pending_count <= 0:
        return None, next_state
    if is_in_cooldown:
        return None, replace(next_state, pending_new_count=pending_count)
    current_count = item.count if item.count is not None else item.total
    text = f"+{pending_count}"
    if current_count is not None:
        text += f", 지금 {current_count}{item.unit or DEFAULT_COUNT_UNIT}"
    line = _build_line(effective, effective.level, text, is_recovery=False)
    return line, replace(next_state, last_alerted_at=now)


def _new_increase(effective: EffectiveItem, baseline: _Baseline) -> int:
    """new 증가분: total 둘 다 있으면 total 차이, 아니면 count 차이 (줄어든 것은 0)"""
    item = effective.item
    if item.total is not None and baseline.total is not None:
        return max(item.total - baseline.total, 0)
    if item.count is not None and baseline.count is not None:
        return max(item.count - baseline.count, 0)
    return 0


def _hold_undelivered_state(effective: EffectiveItem, baseline: _Baseline, alert_state: AttentionItemAlertState,
                            next_state: AttentionItemAlertState) -> AttentionItemAlertState:
    """발송 실패 시 기준: 보낸 시각 유지 + new는 이번 증가분까지 pending_new_count에 누적,
    그 외 규칙은 처리 전 비교 기준(수준·상태·기준 넘김) 유지 > 다음 처리에서 같은 줄 재평가"""
    if effective.rule == ALERT_RULE_NEW:
        pending_count = alert_state.pending_new_count + _new_increase(effective, baseline)
        return replace(next_state, last_alerted_at=alert_state.last_alerted_at, pending_new_count=pending_count)
    return replace(alert_state, last_alerted_total=baseline.total, last_alerted_count=baseline.count,
                   last_alerted_level=baseline.level, last_alerted_state=baseline.state,
                   is_threshold_exceeded=baseline.is_threshold_exceeded)


def _evaluate_threshold(effective: EffectiveItem, baseline: _Baseline, is_exceeded: bool) -> AlertLine | None:
    """threshold: 기준 없으면 없음, 미초과 > 초과 1줄, 초과 > 미초과 해소 1줄"""
    if effective.threshold is None or is_exceeded == baseline.is_threshold_exceeded:
        return None
    unit = effective.item.unit or ""
    value_text = f"{_format_number(effective.item.value)}{unit}"
    threshold_text = f"{_format_number(effective.threshold)}{unit}"
    if is_exceeded:
        return _build_line(effective, effective.level, f"{value_text}, 기준 {threshold_text} 넘음", is_recovery=False)
    return _build_line(effective, _recovery_level(effective, baseline),
                       f"{value_text}, 기준 {threshold_text} 아래로 내려옴", is_recovery=True)


def _evaluate_state(effective: EffectiveItem, baseline: _Baseline) -> AlertLine | None:
    """state: ok > 비ok 1줄, 비ok > ok 해소 1줄, 비ok끼리 바뀜 1줄 (상태값 없음·그대로면 없음)"""
    current_state = effective.item.state
    previous_state = baseline.state
    if current_state is None or previous_state is None or current_state == previous_state:
        return None
    text = f"상태 {previous_state} > {current_state}"
    if current_state == STATE_OK:
        return _build_line(effective, _recovery_level(effective, baseline), text, is_recovery=True)
    return _build_line(effective, effective.level, text, is_recovery=False)


def _evaluate_level(effective: EffectiveItem, baseline: _Baseline) -> AlertLine | None:
    """level: 유효 수준이 올라가고 warning 이상일 때만 1줄 (내려가면 없음)"""
    is_raised = level_rank(effective.level) > level_rank(baseline.level)
    if not is_raised or level_rank(effective.level) < level_rank(LEVEL_RULE_MINIMUM):
        return None
    return _build_line(effective, effective.level, f"수준 {baseline.level or LEVEL_OK} > {effective.level}",
                       is_recovery=False)


def _build_line(effective: EffectiveItem, level: str, text: str, is_recovery: bool) -> AlertLine:
    """알림 줄 (detail 있으면 설명 뒤에 붙임)"""
    if effective.item.detail:
        text = f"{text}{DETAIL_SEPARATOR}{effective.item.detail}"
    return AlertLine(key=effective.item.key, label=effective.label, level=level,
                     admin_url=effective.item.admin_url, text=text, channel_kind=effective.channel_kind,
                     is_recovery=is_recovery)


def _recovery_level(effective: EffectiveItem, baseline: _Baseline) -> str:
    """해소 줄 수준: 해소 전 수준 (수준 정책 ok로 고정이면 ok = 줄 없음)"""
    if effective.level == LEVEL_OK and effective.level != effective.item.level:
        return LEVEL_OK
    return max(baseline.level or LEVEL_OK, effective.level, key=level_rank)


def _previous_effective_level(effective: EffectiveItem, previous_item: StoredAttentionItem | None) -> str | None:
    """이전 항목의 유효 수준 (고정 수준 정책이면 지금과 같은 고정값)"""
    if previous_item is None:
        return None
    is_fixed_policy = effective.level != effective.item.level
    return effective.level if is_fixed_policy else previous_item.level


def _is_threshold_exceeded(value: float | None, threshold: float | None) -> bool:
    """value >= 기준 (둘 중 하나라도 없으면 미초과)"""
    return value is not None and threshold is not None and value >= threshold


def _first_present(*candidates):
    """None 아닌 첫 값 (전부 None이면 None)"""
    return next((candidate for candidate in candidates if candidate is not None), None)


def _format_number(number: float | None) -> str:
    """숫자 표시 (정수면 소수점 없이, 아니면 소수 둘째 자리까지)"""
    if number is None:
        return "-"
    if float(number).is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")
