"""관제소 관리자 overview 조립: 등록 정보 + 폴러 스냅샷 + 저장소 > JSON 직렬화용 dict
서비스 항목은 retired 제외, 점검 대상 주소·토큰은 싣지 않음
"""
from __future__ import annotations

from datetime import datetime, timedelta

from service.control_tower.check_runner import CheckResult
from service.control_tower.poller_steps import merge_maintenance
from service.control_tower.registry import (
    SERVICE_STATUS_PAUSED, SERVICE_STATUS_RETIRED, MaintenanceWindow, Registry, ServiceSpec,
)
from service.control_tower.state_machine import STATUS_DOWN, STATUS_UNKNOWN, STATUS_UP, STATUS_DEGRADED

# 장애 목록: 최근 14일 시작 + 진행 중, 최대 건수
INCIDENT_WINDOW = timedelta(days=14)
INCIDENT_LIMIT = 50
# 최근 이벤트 최대 건수
EVENT_LIMIT = 50
# meta: 직전 심박 성공 여부 ('1' 성공, '0' 실패) / 마지막 심박 성공 시각 / 등록 파일 오류 / 온보딩 적용 해시
META_HEARTBEAT_IS_OK = "heartbeat_is_ok"
META_HEARTBEAT_LAST_OK_AT = "heartbeat_last_ok_at"
META_REGISTRY_ERROR = "registry_error"
META_ONBOARDING_HASH = "discord_onboarding_hash"


def build_overview(runtime, now: datetime) -> dict:
    """overview 본문: 서비스 > 요약 > 장애 > 이벤트 > 심박·등록 오류·온보딩"""
    store = runtime.store
    snapshot = runtime.poller.snapshot() if runtime.poller is not None else None
    registry = runtime.registry_provider()
    states = snapshot.states if snapshot is not None else {}
    observations = snapshot.observations if snapshot is not None else {}
    maintenance = merge_maintenance(registry, store.active_maintenance(now))

    services = [
        _service_entry(service, states.get(service.id), observations.get(service.id), maintenance.get(service.id), now)
        for service in _listed_services(registry)
    ]
    return {
        "projects": [{"id": project.id, "name": project.name} for project in registry.projects],
        "services": services,
        "summary": _summarize(services),
        "incidents": [_incident_entry(incident) for incident in store.recent_incidents(INCIDENT_LIMIT, now - INCIDENT_WINDOW)],
        "events": [_event_entry(event) for event in store.recent_events(EVENT_LIMIT)],
        "registry_error": store.get_meta(META_REGISTRY_ERROR) or None,
        "heartbeat": _heartbeat_entry(store),
        "onboarding": {"is_applied": bool(store.get_meta(META_ONBOARDING_HASH))},
        "last_tick_at": _iso(snapshot.last_tick_at) if snapshot is not None else None,
    }


def _listed_services(registry: Registry) -> list[ServiceSpec]:
    """프로젝트 서비스 > 인프라 순, retired 제외"""
    return [service for service in registry.services + registry.infrastructure
            if service.status != SERVICE_STATUS_RETIRED]


def _service_entry(service: ServiceSpec, state, observation, window: MaintenanceWindow | None, now: datetime) -> dict:
    is_external_known = observation is not None and observation.is_external_known
    return {
        "id": service.id,
        "name": service.name,
        "project_id": service.project_id,
        "lifecycle": service.status,  # active | paused
        "status": state.status if state is not None else STATUS_UNKNOWN,
        "cause": state.cause if state is not None else None,
        "since": _iso(state.since) if state is not None else None,
        "internal": _check_entry(observation.internal if observation is not None else None),
        "external": _check_entry(observation.external if is_external_known else None),
        "is_public": service.is_public,
        "maintenance": _maintenance_entry(window, now),
    }


def _check_entry(check: CheckResult | None) -> dict | None:
    if check is None:
        return None
    return {"is_ok": check.is_ok, "is_slow": check.is_slow, "status_code": check.status_code,
            "latency_milliseconds": check.latency_milliseconds, "error": check.error,
            "checked_at": _iso(check.checked_at)}


def _maintenance_entry(window: MaintenanceWindow | None, now: datetime) -> dict | None:
    """진행 중인 점검 창만 (만료는 null)"""
    if window is None or window.until <= now:
        return None
    return {"until": _iso(window.until), "reason": window.reason}


def _summarize(services: list[dict]) -> dict:
    """서비스당 1칸: 확인 필요(paused) > 점검 > 장애 > 정상 (대기 중 unknown은 세지 않음)"""
    summary = {"ok": 0, "down": 0, "maintenance": 0, "needs_attention": 0}
    for service in services:
        if service["lifecycle"] == SERVICE_STATUS_PAUSED:
            summary["needs_attention"] += 1
        elif service["maintenance"] is not None:
            summary["maintenance"] += 1
        elif service["status"] == STATUS_DOWN:
            summary["down"] += 1
        elif service["status"] in (STATUS_UP, STATUS_DEGRADED):
            summary["ok"] += 1
    return summary


def _incident_entry(incident: dict) -> dict:
    return {"id": incident["id"], "service_id": incident["service_id"], "cause": incident["cause"],
            "started_at": _iso(incident["started_at"]), "ended_at": _iso(incident["ended_at"])}


def _event_entry(event: dict) -> dict:
    return {"id": event["id"], "project_id": event["project_id"], "kind": event["kind"],
            "created_at": _iso(event["created_at"])}


def _heartbeat_entry(store) -> dict:
    """심박: is_ok None = 기록 없음 (Worker 미설정 포함)"""
    is_ok_text = store.get_meta(META_HEARTBEAT_IS_OK)
    return {"last_ok_at": store.get_meta(META_HEARTBEAT_LAST_OK_AT),
            "is_ok": None if is_ok_text is None else is_ok_text == "1"}


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None
