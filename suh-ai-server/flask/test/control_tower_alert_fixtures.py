"""관제소 알림 계획 테스트 공통: 등록 정보(NAS 하위 + 단독 서비스), 상태·전이 생성, 계획 호출"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from service.control_tower.alert_planner import plan_notifications
from service.control_tower.registry import ProjectSpec, Registry, ServiceSpec
from service.control_tower.state_machine import INITIAL_STATE, ServiceState, Transition

BASE_TIME = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)  # KST 09:00
DOWN_SINCE = BASE_TIME - timedelta(minutes=3)  # KST 08:57
GRACE = timedelta(minutes=10)  # AlertPolicy.parent_recovery_grace_minutes 기본값

REGISTRY = Registry(
    projects=(ProjectSpec("elum", "이룸"), ProjectSpec("romrom", "롬롬")),
    services=(
        ServiceSpec("elum-api", "이룸 API", "elum", depends_on="nas"),
        ServiceSpec("elum-web", "이룸 웹", "elum", depends_on="nas"),
        ServiceSpec("romrom-api", "롬롬 API", "romrom", depends_on="nas"),
        ServiceSpec("romrom-admin", "롬롬 관리자", "romrom", status="paused", depends_on="nas"),
        ServiceSpec("romrom-old", "롬롬 구버전", "romrom", status="retired", depends_on="nas"),
        ServiceSpec("elum-docs", "이룸 문서", "elum"),
    ),
    infrastructure=(
        ServiceSpec("nas", "시놀로지 NAS", None),
        ServiceSpec("home-network", "집 인터넷", None),
    ),
)


def up_state(since: datetime = BASE_TIME - timedelta(days=1), last_notified_at: datetime | None = None) -> ServiceState:
    return replace(INITIAL_STATE, status="up", since=since, last_notified_at=last_notified_at)


def down_state(cause: str = "service_down", is_down_notified: bool = False,
               last_notified_at: datetime | None = None, since: datetime = DOWN_SINCE) -> ServiceState:
    return ServiceState("down", 3, 0, cause, since, last_notified_at, is_down_notified)


def down_transition(service_id: str, cause: str = "service_down", since: datetime = DOWN_SINCE) -> Transition:
    return Transition(service_id, "up", "down", cause, since)


def recovery_transition(service_id: str, since: datetime = DOWN_SINCE, cause: str = "service_down") -> Transition:
    return Transition(service_id, "down", "up", cause, since)


def all_up(registry: Registry = REGISTRY, **overrides: ServiceState) -> dict[str, ServiceState]:
    """전 서비스 up + 덮어쓰기 (키의 _ > -)"""
    states = {service.id: up_state() for service in registry.services + registry.infrastructure}
    states.update({service_id.replace("_", "-"): state for service_id, state in overrides.items()})
    return states


def plan(states, transitions=(), maintenance=None, now=BASE_TIME, registry: Registry = REGISTRY):
    return plan_notifications(registry, states, list(transitions), maintenance or {}, now)


def titles(notifications) -> list[str]:
    return [notification.title for notification in notifications]
