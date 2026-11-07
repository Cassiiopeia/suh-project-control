"""관제소 폴러 틱 단계 도우미: 감시 대상 선별, 내부 점검 병렬 실행, 관측 조립, 외부 결과 신선도, 공개 장애, 점검 창 병합
저장소 접근은 읽기 전용 조회만 (쓰기는 폴러 스레드의 ControlTowerPoller가 담당)
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from service.control_tower.alert_suppression import ACTIVE_STATUS, HOME_NETWORK_ID
from service.control_tower.check_runner import ERROR_LABEL_CONNECTION, CheckResult
from service.control_tower.heartbeat_client import HeartbeatResponse
from service.control_tower.registry import MaintenanceWindow, Registry, ServiceSpec
from service.control_tower.state_machine import Observation

logger = logging.getLogger(__name__)

RETIRED_STATUS = "retired"
# 내부 점검 동시 실행 상한 (스레드 수)
INTERNAL_CHECK_MAX_WORKERS = 16
# Worker 외부 결과 유효 시간: 더 오래되면 '모름' (크론 1분 + 여유)
EXTERNAL_RESULT_MAX_AGE = timedelta(minutes=3)
# 심박에 싣는 공개 장애: 진행 중 + 최근 14일 시작, 최대 건수
PUBLIC_INCIDENT_WINDOW = timedelta(days=14)
PUBLIC_INCIDENT_LIMIT = 100


def monitored_services(registry: Registry) -> list[ServiceSpec]:
    """감시 대상: 인프라 + 프로젝트 서비스 중 retired 제외"""
    return [service for service in registry.infrastructure + registry.services if service.status != RETIRED_STATUS]


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


def fresh_external_results(response: HeartbeatResponse | None, now: datetime) -> dict[str, CheckResult]:
    """심박 응답 > 유효 시간 안의 외부 결과만 (심박 실패·시각 없음·오래됨 > 빈 dict = 전부 모름)"""
    if response is None or response.checked_at is None:
        return {}
    if now - response.checked_at > EXTERNAL_RESULT_MAX_AGE:
        return {}
    return response.external_results


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


def build_public_incidents(registry: Registry, store, now: datetime) -> list[dict]:
    """공개·활성 서비스의 진행 중 + 최근 14일 장애 > {service_id, started_at, ended_at} (UTC ISO, 진행 중 null)"""
    public_service_ids = {
        service.id for service in registry.services if service.is_public and service.status == ACTIVE_STATUS
    }
    incidents = store.recent_incidents(PUBLIC_INCIDENT_LIMIT, now - PUBLIC_INCIDENT_WINDOW)
    return [
        {"service_id": incident["service_id"], "started_at": _to_utc_iso(incident["started_at"]),
         "ended_at": _to_utc_iso(incident["ended_at"])}
        for incident in incidents if incident["service_id"] in public_service_ids
    ]


def merge_maintenance(registry: Registry,
                      stored_windows: dict[str, MaintenanceWindow]) -> dict[str, MaintenanceWindow]:
    """점검 창 병합: 등록 파일 창 + 관리자 화면 창 (같은 서비스는 관리자 화면 우선)"""
    merged = {window.service_id: window for window in registry.maintenance}
    merged.update(stored_windows)
    return merged


def _to_utc_iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).isoformat() if moment is not None else None
