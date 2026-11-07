"""관제소 폴러 틱 단계 도우미: 감시 대상 선별, 내부 점검 병렬 실행, 관측 조립, 외부 결과 신선도, 발송 실패 플래그 복원, 공개 장애, 점검 창 병합
저장소 접근은 읽기 전용 조회만 (쓰기는 폴러 스레드의 ControlTowerPoller가 담당)
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Mapping

from service.control_tower.alert_planner import SEVERITY_CRITICAL, Notification
from service.control_tower.alert_suppression import HOME_NETWORK_ID
from service.control_tower.check_runner import ERROR_LABEL_CONNECTION, CheckResult
from service.control_tower.heartbeat_client import HeartbeatResponse
from service.control_tower.registry import (
    SERVICE_STATUS_ACTIVE, SERVICE_STATUS_RETIRED, MaintenanceWindow, Registry, ServiceSpec,
)
from service.control_tower.state_machine import STATUS_DOWN, Observation, ServiceState

logger = logging.getLogger(__name__)

# 내부 점검 동시 실행 상한 (스레드 수)
INTERNAL_CHECK_MAX_WORKERS = 16
# Worker 외부 결과 유효 시간: 더 오래되면 '모름' (크론 1분 + 여유)
EXTERNAL_RESULT_MAX_AGE = timedelta(minutes=3)
# 심박에 싣는 공개 장애: 진행 중 + 최근 14일 시작, 최대 건수
PUBLIC_INCIDENT_WINDOW = timedelta(days=14)
PUBLIC_INCIDENT_LIMIT = 100


def monitored_services(registry: Registry) -> list[ServiceSpec]:
    """감시 대상: 인프라 + 프로젝트 서비스 중 retired 제외"""
    return [
        service for service in registry.infrastructure + registry.services if service.status != SERVICE_STATUS_RETIRED
    ]


def run_internal_checks(services: list[ServiceSpec], check_runner, slow_milliseconds: int) -> dict[str, CheckResult]:
    """내부 점검 병렬 실행 > service_id별 결과 (실행기 예외는 데이터 없음으로 제외)"""
    targets = [service for service in services if service.internal is not None]
    if not targets:
        return {}
    worker_count = min(INTERNAL_CHECK_MAX_WORKERS, len(targets))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="control-tower-check") as executor:
        future_by_service_id = {
            service.id: executor.submit(check_runner, service.internal, slow_milliseconds) for service in targets
        }
    results: dict[str, CheckResult] = {}
    for service_id, future in future_by_service_id.items():
        try:
            results[service_id] = future.result()
        except Exception as error:  # 점검 실행기 자체 오류: 서비스 장애로 보지 않음
            logger.warning("[control-tower poller] internal check crashed : service %s : %s",
                           service_id, type(error).__name__)
    return results


def heartbeat_check_result(is_heartbeat_ok: bool, now: datetime) -> CheckResult:
    """심박 성공 여부 > 집 인터넷 내부 관측 결과"""
    return CheckResult(is_heartbeat_ok, False, None, 0, None if is_heartbeat_ok else ERROR_LABEL_CONNECTION, now)


def fresh_external_results(response: HeartbeatResponse | None, now: datetime,
                           last_applied_checked_at: datetime | None) -> dict[str, CheckResult]:
    """심박 응답 > 새 외부 결과만 (심박 실패·시각 없음·오래됨·반영한 checked_at 이하 > 빈 dict = 전부 모름)"""
    if response is None or response.checked_at is None:
        return {}
    if now - response.checked_at > EXTERNAL_RESULT_MAX_AGE:
        return {}
    # Worker 크론 정체·순서 뒤바뀐 응답: 이미 반영한 시각 이하 결과는 버림 (실패 연속·집계 중복 방지)
    if last_applied_checked_at is not None and response.checked_at <= last_applied_checked_at:
        return {}
    return response.external_results


def restore_undelivered_alert_flags(undelivered: list[Notification], advanced_states: dict[str, ServiceState],
                                    planned_states: dict[str, ServiceState]) -> dict[str, ServiceState]:
    """발송 실패한 down·재알림·묶음 > 대상 중 down 서비스의 알림 플래그를 전이 직후 값으로 (다음 틱 재계획)
    복구·요약 알림은 재시도 안 함"""
    restored_states = dict(planned_states)
    for notification in undelivered:
        if notification.severity != SEVERITY_CRITICAL:
            continue
        for service_id in notification.service_ids:
            planned = restored_states.get(service_id)
            advanced = advanced_states.get(service_id)
            if planned is None or advanced is None or planned.status != STATUS_DOWN:
                continue
            restored_states[service_id] = replace(planned, is_down_notified=advanced.is_down_notified,
                                                  last_notified_at=advanced.last_notified_at)
    return restored_states


def build_observations(services: list[ServiceSpec], internal_results: dict[str, CheckResult],
                       external_results: dict[str, CheckResult],
                       heartbeat_check: CheckResult | None) -> dict[str, Observation]:
    """서비스별 관측: 집 인터넷은 심박 결과, 그 외는 내부 결과 + 받은 외부 결과 (점검 없는 항목 제외)"""
    observations: dict[str, Observation] = {}
    for service in services:
        if service.id == HOME_NETWORK_ID:
            if heartbeat_check is not None:
                observations[service.id] = Observation(heartbeat_check, None, False)
            continue
        if service.internal is None and service.external is None:
            continue
        external = external_results.get(service.id) if service.external is not None else None
        observations[service.id] = Observation(internal_results.get(service.id), external, external is not None)
    return observations


def carry_over_external_observations(observations: dict[str, Observation],
                                     previous: Mapping[str, Observation], now: datetime) -> dict[str, Observation]:
    """표시용 관측: 이번 틱에 외부 결과가 없는 서비스는 3분 안의 직전 외부 결과 유지 (판정·저장에는 쓰지 않음)"""
    carried = dict(observations)
    for service_id, observation in observations.items():
        previous_observation = previous.get(service_id)
        if observation.is_external_known or previous_observation is None:
            continue
        previous_external = previous_observation.external
        if (previous_observation.is_external_known and previous_external is not None
                and now - previous_external.checked_at <= EXTERNAL_RESULT_MAX_AGE):
            carried[service_id] = replace(observation, external=previous_external, is_external_known=True)
    return carried


def build_public_incidents(registry: Registry, store, maintenance: Mapping[str, MaintenanceWindow],
                           now: datetime) -> list[dict]:
    """공개·활성 서비스의 진행 중 + 최근 14일 장애 > {service_id, started_at, ended_at} (UTC ISO, 진행 중 null)
    점검 창 안 장애 제외 2종: 점검 중 시작·종료, 진행 중인데 지금 점검 중"""
    public_service_ids = {
        service.id for service in registry.services if service.is_public and service.status == SERVICE_STATUS_ACTIVE
    }
    incidents = store.recent_incidents(PUBLIC_INCIDENT_LIMIT, now - PUBLIC_INCIDENT_WINDOW)
    return [
        {"service_id": incident["service_id"], "started_at": _to_utc_iso(incident["started_at"]),
         "ended_at": _to_utc_iso(incident["ended_at"])}
        for incident in incidents
        if incident["service_id"] in public_service_ids and not _is_hidden_by_maintenance(incident, maintenance, now)
    ]


def is_under_maintenance(maintenance: Mapping[str, MaintenanceWindow], service_id: str, now: datetime) -> bool:
    """서비스가 지금 점검 창 안인지"""
    window = maintenance.get(service_id)
    return window is not None and window.is_active_at(now)


def _is_hidden_by_maintenance(incident: dict, maintenance: Mapping[str, MaintenanceWindow], now: datetime) -> bool:
    """진행 중 > 지금 점검 중이면 숨김, 종료 > 점검 창 안에서 시작·종료했으면 숨김"""
    if incident["ended_at"] is None:
        return is_under_maintenance(maintenance, incident["service_id"], now)
    return incident["is_within_maintenance"]


def merge_maintenance(registry: Registry,
                      stored_windows: dict[str, MaintenanceWindow]) -> dict[str, MaintenanceWindow]:
    """점검 창 병합: 등록 파일 창 + 관리자 화면 창 (같은 서비스는 관리자 화면 우선)"""
    merged = {window.service_id: window for window in registry.maintenance}
    merged.update(stored_windows)
    return merged


def _to_utc_iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).isoformat() if moment is not None else None
