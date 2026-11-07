"""관제소 알림 계획: 상태·전이 > 디스코드 알림 목록 + 알림 플래그 갱신 상태 (순수 함수, I/O·시계 없음)
억제 4종(비활성, 점검 중, 조상 장애, 집 인터넷 장애 중 외부 원인) > down·재알림·복구만 발송 (up<->degraded 없음)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from service.control_tower import alert_texts
from service.control_tower.registry import MaintenanceWindow, Registry, ServiceSpec
from service.control_tower.state_machine import (
    CAUSE_EXTERNAL_PATH, CAUSE_UNREACHABLE, STATUS_DOWN, ServiceState, Transition,
)

# 집 인터넷 인프라 id (Worker 심박 끊김으로 down 판정)
HOME_NETWORK_ID = "home-network"
# 집 인터넷 장애 중 억제할 원인 (외부에서만 보이는 실패)
EXTERNAL_CAUSES = (CAUSE_EXTERNAL_PATH, CAUSE_UNREACHABLE)
ACTIVE_STATUS = "active"

SEVERITY_CRITICAL = "critical"
SEVERITY_RECOVERED = "recovered"
# 인프라: 전역 관제-긴급 / 프로젝트 서비스: 프로젝트 상태 채널
GLOBAL_SCOPE = "global"
INFRASTRUCTURE_KIND = "alert"
PROJECT_SERVICE_KIND = "status"

SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class Notification:
    scope: str  # project id | 'global'
    kind: str  # 'status' | 'alert' | 'digest'
    severity: str  # critical | warning | info | recovered
    title: str
    body: str
    service_ids: tuple[str, ...]  # 첫 항목 = 알림 주체, 나머지 = 영향·함께 복구된 서비스
    dedupe_key: str  # {service_id}:{down|reminder-N|recovered}:{장애 시작 iso}


@dataclass(frozen=True)
class _PlanContext:
    registry: Registry
    states: dict[str, ServiceState]
    recovery_by_id: dict[str, Transition]  # 이번 호출의 down 복구 전이
    maintenance: dict[str, MaintenanceWindow]
    now: datetime


def plan_notifications(registry: Registry, states: dict[str, ServiceState], transitions: list[Transition],
                       maintenance: dict[str, MaintenanceWindow],
                       now: datetime) -> tuple[list[Notification], dict[str, ServiceState]]:
    """알림 계획: 복구 알림(전이 기준) > down·재알림(상태 기준, 인프라 먼저) > 갱신 상태 반환"""
    recovery_by_id = {
        transition.service_id: transition for transition in transitions if transition.before == STATUS_DOWN
    }
    context = _PlanContext(registry, states, recovery_by_id, maintenance, now)
    notifications: list[Notification] = []
    new_states = dict(states)

    # 복구 알림
    for transition in recovery_by_id.values():
        recovery = _plan_recovery(context, transition)
        if recovery is not None:
            notifications.append(recovery)

    # down 알림·재알림
    for service in registry.infrastructure + registry.services:
        state = states.get(service.id)
        if state is None or state.status != STATUS_DOWN or _is_down_suppressed(context, service, state):
            continue
        notification, updated_state = _plan_down_or_reminder(context, service, state)
        new_states[service.id] = updated_state
        if notification is not None:
            notifications.append(notification)
    return notifications, new_states


def _is_down_suppressed(context: _PlanContext, service: ServiceSpec, state: ServiceState) -> bool:
    """down 알림 억제 판정 (비활성, 점검 중, 조상 장애, 집 인터넷 장애 중 외부 원인), 플래그는 건드리지 않음"""
    if service.status != ACTIVE_STATUS or _is_in_maintenance(context, service.id):
        return True
    if _has_ancestor_outage(context, service):
        return True
    is_external_cause = state.cause in EXTERNAL_CAUSES
    return is_external_cause and service.id != HOME_NETWORK_ID and _is_outage_ongoing(context, HOME_NETWORK_ID)


def _is_in_maintenance(context: _PlanContext, service_id: str) -> bool:
    window = context.maintenance.get(service_id)
    return window is not None and context.now < window.until


def _is_outage_ongoing(context: _PlanContext, service_id: str) -> bool:
    """down 중이거나 이번 호출에서 막 복구됨 (자식 개별 알림은 다음 호출부터)"""
    state = context.states.get(service_id)
    is_down = state is not None and state.status == STATUS_DOWN
    return is_down or service_id in context.recovery_by_id


def _has_ancestor_outage(context: _PlanContext, service: ServiceSpec) -> bool:
    """depends_on 사슬을 따라 올라가며 장애 중인 조상 확인 (순환 방지)"""
    visited = {service.id}
    parent_id = service.depends_on
    while parent_id is not None and parent_id not in visited:
        if _is_outage_ongoing(context, parent_id):
            return True
        visited.add(parent_id)
        parent = context.registry.service_by_id(parent_id)
        parent_id = parent.depends_on if parent is not None else None
    return False


def _plan_down_or_reminder(context: _PlanContext, service: ServiceSpec,
                           state: ServiceState) -> tuple[Notification | None, ServiceState]:
    """미알림 > down 알림 / 알림 시각 없음 > 기준 시각만 기록 / 재알림 간격 경과 > 재알림"""
    now = context.now
    since = state.since or now
    affected = _down_descendants(context, service)
    affected_names = [child.name for child in affected]
    service_ids = (service.id, *(child.id for child in affected))
    notified_state = replace(state, is_down_notified=True, last_notified_at=now)

    if not state.is_down_notified:
        body = alert_texts.down_body(state.cause, since, affected_names)
        return _build(service, SEVERITY_CRITICAL, alert_texts.down_title(service.name), body,
                      service_ids, "down", since), notified_state

    # 복원된 상태에 알림 시각 없음 (재알림 기준만 지금으로)
    if state.last_notified_at is None:
        return None, replace(state, last_notified_at=now)

    reminder_seconds = context.registry.alert.reminder_hours * SECONDS_PER_HOUR
    if (now - state.last_notified_at).total_seconds() < reminder_seconds:
        return None, state

    # 재알림 번호: 장애 시작 후 경과한 재알림 간격 수 (매 재알림마다 증가)
    reminder_number = max(1, int((now - since).total_seconds() // reminder_seconds))
    body = alert_texts.reminder_body(state.cause, since, now, affected_names)
    return _build(service, SEVERITY_CRITICAL, alert_texts.reminder_title(service.name), body,
                  service_ids, f"reminder-{reminder_number}", since), notified_state


def _plan_recovery(context: _PlanContext, transition: Transition) -> Notification | None:
    """복구 알림: 활성·점검 외·이번 장애를 알린 서비스만 > 다운 시간 + 함께 복구된 하위 서비스"""
    service = context.registry.service_by_id(transition.service_id)
    if service is None or service.status != ACTIVE_STATUS or _is_in_maintenance(context, service.id):
        return None
    if not _was_outage_notified(context, transition):
        return None

    # 개별 알림 없이 함께 복구된 하위 서비스 (부모 억제로 묻혀 있던 것)
    recovered_children = [
        child for child in _active_descendants(context.registry, service)
        if child.id in context.recovery_by_id
        and not _was_outage_notified(context, context.recovery_by_id[child.id])
    ]
    body = alert_texts.recovery_body(transition.cause, transition.since, context.now,
                                     [child.name for child in recovered_children])
    service_ids = (service.id, *(child.id for child in recovered_children))
    return _build(service, SEVERITY_RECOVERED, alert_texts.recovery_title(service.name), body,
                  service_ids, "recovered", transition.since)


def _was_outage_notified(context: _PlanContext, transition: Transition) -> bool:
    """이번 장애 알림 여부: 마지막 알림 시각 >= 장애 시작 (advance가 복구 시 is_down_notified를 지우므로)"""
    state = context.states.get(transition.service_id)
    return state is not None and state.last_notified_at is not None and state.last_notified_at >= transition.since


def _down_descendants(context: _PlanContext, service: ServiceSpec) -> list[ServiceSpec]:
    """현재 down인 활성 하위 서비스 (부모 알림 '영향 서비스' 목록)"""
    return [
        child for child in _active_descendants(context.registry, service)
        if (state := context.states.get(child.id)) is not None and state.status == STATUS_DOWN
    ]


def _active_descendants(registry: Registry, service: ServiceSpec) -> list[ServiceSpec]:
    """depends_on 하위 전체 중 활성만 (깊이 우선, 등록 순서, 순환 방지)"""
    descendants: list[ServiceSpec] = []
    visited = {service.id}
    pending = list(registry.children_of(service.id))
    while pending:
        child = pending.pop(0)
        if child.id in visited:
            continue
        visited.add(child.id)
        if child.status == ACTIVE_STATUS:
            descendants.append(child)
        pending[:0] = registry.children_of(child.id)
    return descendants


def _build(service: ServiceSpec, severity: str, title: str, body: str, service_ids: tuple[str, ...],
           event: str, since: datetime) -> Notification:
    """서비스 종류별 경로(인프라 > 전역 alert, 프로젝트 > 프로젝트 status) + 중복 키 조립"""
    is_infrastructure = service.project_id is None
    scope = GLOBAL_SCOPE if is_infrastructure else service.project_id
    kind = INFRASTRUCTURE_KIND if is_infrastructure else PROJECT_SERVICE_KIND
    return Notification(scope, kind, severity, title, body, service_ids,
                        f"{service.id}:{event}:{since.isoformat()}")
