"""관제소 down 알림 처리 판정: 알림 없음 / 개별 / 묶음 (생명주기, 점검 중, 조상 사슬, 집 인터넷, 복구 유예)
조상 상태 3종이 자식을 막음: down, 실패 연속 중(미알림 자식만), 복구 알림 후 유예 시간 이내
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from service.control_tower.registry import SERVICE_STATUS_ACTIVE, MaintenanceWindow, Registry, ServiceSpec
from service.control_tower.state_machine import (
    CAUSE_EXTERNAL_PATH, CAUSE_UNREACHABLE, STATUS_DEGRADED, STATUS_DOWN, STATUS_UP, ServiceState, Transition,
)

# 집 인터넷 인프라 id (Worker 심박 끊김으로 down 판정)
HOME_NETWORK_ID = "home-network"
# 집 인터넷 장애 중 억제할 원인 (외부에서만 보이는 실패)
EXTERNAL_CAUSES = (CAUSE_EXTERNAL_PATH, CAUSE_UNREACHABLE)
# 복구 알림 시각 판정 대상 상태 (down 중 재알림 시각과 구분)
RECOVERED_STATUSES = (STATUS_UP, STATUS_DEGRADED)

# down 서비스 처리 3종
HANDLING_SILENT = "silent"  # 알림 없음, 플래그 그대로
HANDLING_INDIVIDUAL = "individual"  # 개별 down·재알림
HANDLING_BUNDLE = "bundle"  # 기준 조상의 '복구 후 계속 down' 묶음


@dataclass(frozen=True)
class AlertContext:
    registry: Registry
    states: dict[str, ServiceState]
    recovery_by_id: dict[str, Transition]  # 이번 호출의 down 복구 전이
    maintenance: dict[str, MaintenanceWindow]
    now: datetime


@dataclass(frozen=True)
class DownHandling:
    action: str  # HANDLING_*
    bundle_anchor_id: str | None = None  # bundle일 때 묶음 기준 조상 (또는 home-network)


SILENT = DownHandling(HANDLING_SILENT)
INDIVIDUAL = DownHandling(HANDLING_INDIVIDUAL)


def decide_down_handling(context: AlertContext, service: ServiceSpec, state: ServiceState) -> DownHandling:
    """down 서비스 처리: 비활성·점검 중 > 막는 조상 > 집 인터넷(외부 원인) > 알림 완료면 개별 > 묶음 기준 > 개별"""
    if service.status != SERVICE_STATUS_ACTIVE or is_in_maintenance(context, service.id):
        return SILENT
    anchors = active_ancestors(context.registry, service)
    if any(_is_blocking(context, ancestor, state) for ancestor in anchors):
        return SILENT

    # 집 인터넷: 외부 원인만 막고 묶음 기준 후보로 추가 (자기 자신 제외)
    home_network = context.registry.service_by_id(HOME_NETWORK_ID)
    is_external_cause = state.cause in EXTERNAL_CAUSES and service.id != HOME_NETWORK_ID
    if is_external_cause and home_network is not None and home_network.status == SERVICE_STATUS_ACTIVE:
        if _is_blocking(context, home_network, state):
            return SILENT
        anchors = [*anchors, home_network]

    if state.is_down_notified:
        return INDIVIDUAL
    anchor_id = _find_bundle_anchor_id(context, anchors, state)
    return DownHandling(HANDLING_BUNDLE, anchor_id) if anchor_id is not None else INDIVIDUAL


def is_in_maintenance(context: AlertContext, service_id: str) -> bool:
    window = context.maintenance.get(service_id)
    return window is not None and window.is_active_at(context.now)


def active_ancestors(registry: Registry, service: ServiceSpec) -> list[ServiceSpec]:
    """depends_on 사슬의 활성 조상 (가까운 순, 비활성은 건너뛰고 계속, 순환 방지)"""
    ancestors: list[ServiceSpec] = []
    visited = {service.id}
    parent_id = service.depends_on
    while parent_id is not None and parent_id not in visited:
        visited.add(parent_id)
        parent = registry.service_by_id(parent_id)
        if parent is None:
            break
        if parent.status == SERVICE_STATUS_ACTIVE:
            ancestors.append(parent)
        parent_id = parent.depends_on
    return ancestors


def _is_blocking(context: AlertContext, ancestor: ServiceSpec, child_state: ServiceState) -> bool:
    """조상이 자식 알림을 막는지 (down / 실패 연속 중이고 자식 미알림 / 복구 후 유예 이내)"""
    ancestor_state = context.states.get(ancestor.id)
    if ancestor_state is None:
        return False
    if ancestor_state.status == STATUS_DOWN:
        return True
    if ancestor_state.consecutive_failures > 0 and not child_state.is_down_notified:
        return True
    return _is_within_recovery_grace(context, ancestor_state)


def recovery_alerted_at(state: ServiceState | None) -> datetime | None:
    """복구 알림 시각: up/degraded + down 알림 플래그 없음 + 마지막 알림 시각 (그 외 None)"""
    if state is None or state.status not in RECOVERED_STATUSES or state.is_down_notified:
        return None
    return state.last_notified_at


def _is_within_recovery_grace(context: AlertContext, ancestor_state: ServiceState) -> bool:
    """복구 알림 후 유예 시간 이내인지 (조용히 복구된 조상은 유예 없음)"""
    alerted_at = recovery_alerted_at(ancestor_state)
    if alerted_at is None:
        return False
    grace = timedelta(minutes=context.registry.alert.parent_recovery_grace_minutes)
    return context.now - alerted_at < grace


def _find_bundle_anchor_id(context: AlertContext, anchors: list[ServiceSpec], child_state: ServiceState) -> str | None:
    """가장 가까운 묶음 기준: 자식 장애가 조상 복구 알림 이전부터 이어진 경우"""
    if child_state.since is None:
        return None
    for anchor in anchors:
        alerted_at = recovery_alerted_at(context.states.get(anchor.id))
        if alerted_at is not None and child_state.since <= alerted_at:
            return anchor.id
    return None
