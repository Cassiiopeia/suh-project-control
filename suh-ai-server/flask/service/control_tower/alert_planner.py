"""관제소 알림 계획: 상태·전이 > 디스코드 알림 목록 + 알림 플래그 갱신 상태 (순수 함수, I/O·시계 없음)
발송 4종: 복구, down, 재알림, 복구 후 계속 down 묶음 (up<->degraded 없음, 억제 판정은 alert_suppression)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from service.control_tower import alert_texts
from service.control_tower.alert_suppression import (
    HANDLING_BUNDLE, HANDLING_INDIVIDUAL, AlertContext, decide_down_handling, is_in_maintenance,
    recovery_alerted_at,
)
from service.control_tower.registry import SERVICE_STATUS_ACTIVE, MaintenanceWindow, Registry, ServiceSpec
from service.control_tower.state_machine import STATUS_DOWN, ServiceState, Transition

SEVERITY_CRITICAL = "critical"
SEVERITY_RECOVERED = "recovered"
# 인프라: 전역 관제-긴급 / 프로젝트 서비스: 프로젝트 상태 채널
GLOBAL_SCOPE = "global"
INFRASTRUCTURE_KIND = "alert"
PROJECT_SERVICE_KIND = "status"


@dataclass(frozen=True)
class Notification:
    scope: str  # project id | 'global'
    kind: str  # 'status' | 'alert' | 'digest'
    severity: str  # critical | warning | info | recovered
    title: str
    body: str
    service_ids: tuple[str, ...]  # 첫 항목 = 알림 주체, 나머지 = 영향·함께 복구·계속 down 서비스
    dedupe_key: str  # {service_id}:{down|reminder-N|recovered|still-down}:{기준 시각 iso}
    link_url: str | None = None  # 임베드 제목 링크 (없으면 상태 페이지)


def plan_notifications(registry: Registry, states: dict[str, ServiceState], transitions: list[Transition],
                       maintenance: dict[str, MaintenanceWindow],
                       now: datetime) -> tuple[list[Notification], dict[str, ServiceState]]:
    """알림 계획: 복구(전이 기준) > down 처리 판정(상태 기준, 인프라 먼저) > 개별 down·재알림 > 묶음"""
    recovery_by_id = {
        transition.service_id: transition for transition in transitions if transition.before == STATUS_DOWN
    }
    context = AlertContext(registry, states, recovery_by_id, maintenance, now)
    notifications: list[Notification] = []
    new_states = dict(states)

    # 복구 알림 (알림 시각 기록 = 자식 유예·묶음 기준)
    for transition in recovery_by_id.values():
        recovery = _plan_recovery(context, transition)
        if recovery is not None:
            notifications.append(recovery)
            new_states[transition.service_id] = replace(states[transition.service_id], last_notified_at=now)

    # down 처리는 복구 알림 반영 상태로 판정 (같은 틱 자식 보류)
    context = replace(context, states=dict(new_states))

    # down 처리: 개별은 바로, 묶음은 기준 조상별로 모음 (등록 순서 유지)
    bundled_by_anchor_id: dict[str, list[ServiceSpec]] = {}
    for service in registry.infrastructure + registry.services:
        state = states.get(service.id)
        if state is None or state.status != STATUS_DOWN:
            continue
        handling = decide_down_handling(context, service, state)
        if handling.action == HANDLING_BUNDLE:
            bundled_by_anchor_id.setdefault(handling.bundle_anchor_id, []).append(service)
        elif handling.action == HANDLING_INDIVIDUAL:
            notification, new_states[service.id] = _plan_down_or_reminder(context, service, state)
            if notification is not None:
                notifications.append(notification)

    # 복구 후 계속 down 묶음 (포함된 자식은 알림 완료 처리 > 이후 개별 복구·재알림)
    for anchor_id, children in bundled_by_anchor_id.items():
        notifications.append(_plan_still_down_bundle(context, anchor_id, children))
        for child in children:
            new_states[child.id] = replace(states[child.id], is_down_notified=True, last_notified_at=now)
    return notifications, new_states


def _plan_down_or_reminder(context: AlertContext, service: ServiceSpec,
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
        return _build_notification(service, SEVERITY_CRITICAL, alert_texts.down_title(service.name), body,
                                   service_ids, "down", since), notified_state

    # 복원된 상태에 알림 시각 없음 (재알림 기준만 지금으로)
    if state.last_notified_at is None:
        return None, replace(state, last_notified_at=now)

    reminder_interval = timedelta(hours=context.registry.alert.reminder_hours)
    if now - state.last_notified_at < reminder_interval:
        return None, state

    # 재알림 번호: 장애 시작 후 경과한 재알림 간격 수 (매 재알림마다 증가)
    reminder_number = max(1, (now - since) // reminder_interval)
    body = alert_texts.reminder_body(state.cause, since, now, affected_names)
    return _build_notification(service, SEVERITY_CRITICAL, alert_texts.reminder_title(service.name), body,
                               service_ids, f"reminder-{reminder_number}", since), notified_state


def _plan_still_down_bundle(context: AlertContext, anchor_id: str, children: list[ServiceSpec]) -> Notification:
    """유예 종료 후에도 down인 미알림 하위 서비스 > 기준 조상 이름으로 1건 (기준 시각 = 조상 복구 알림 시각)"""
    anchor = context.registry.service_by_id(anchor_id)
    anchor_recovered_at = recovery_alerted_at(context.states.get(anchor_id)) or context.now
    body = alert_texts.still_down_bundle_body([(child.name, context.states[child.id].cause) for child in children])
    service_ids = (anchor_id, *(child.id for child in children))
    return _build_notification(anchor, SEVERITY_CRITICAL, alert_texts.still_down_bundle_title(anchor.name), body,
                               service_ids, "still-down", anchor_recovered_at)


def _plan_recovery(context: AlertContext, transition: Transition) -> Notification | None:
    """복구 알림: 활성·점검 외·이번 장애를 알린 서비스만 > 다운 시간 + 함께 복구된 하위 서비스"""
    service = context.registry.service_by_id(transition.service_id)
    if service is None or service.status != SERVICE_STATUS_ACTIVE or is_in_maintenance(context, service.id):
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
    return _build_notification(service, SEVERITY_RECOVERED, alert_texts.recovery_title(service.name), body,
                               service_ids, "recovered", transition.since)


def _was_outage_notified(context: AlertContext, transition: Transition) -> bool:
    """이번 장애 알림 여부: 마지막 알림 시각 >= 장애 시작 (advance가 복구 시 is_down_notified를 지우므로)"""
    state = context.states.get(transition.service_id)
    return state is not None and state.last_notified_at is not None and state.last_notified_at >= transition.since


def _down_descendants(context: AlertContext, service: ServiceSpec) -> list[ServiceSpec]:
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
        if child.status == SERVICE_STATUS_ACTIVE:
            descendants.append(child)
        pending[:0] = registry.children_of(child.id)
    return descendants


def _build_notification(service: ServiceSpec, severity: str, title: str, body: str, service_ids: tuple[str, ...],
                        event: str, since: datetime) -> Notification:
    """서비스 종류별 경로(인프라 > 전역 alert, 프로젝트 > 프로젝트 status) + 중복 키 조립"""
    is_infrastructure = service.project_id is None
    scope = GLOBAL_SCOPE if is_infrastructure else service.project_id
    kind = INFRASTRUCTURE_KIND if is_infrastructure else PROJECT_SERVICE_KIND
    return Notification(scope, kind, severity, title, body, service_ids,
                        f"{service.id}:{event}:{since.isoformat()}")
