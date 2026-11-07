"""관제소 상태 기계: 점검 관측 > 서비스 상태·전이 (순수 함수, I/O·시계 없음)"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from service.control_tower.check_runner import CheckResult
from service.control_tower.registry import AlertPolicy

STATUS_UP = "up"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"  # 기동 직후 첫 관측 전

CAUSE_SERVICE_DOWN = "service_down"  # 내부 점검 실패
CAUSE_EXTERNAL_PATH = "external_path"  # 내부 정상 + 외부 경로 실패
CAUSE_UNREACHABLE = "unreachable"  # 내부 점검 없음 + 외부 실패


@dataclass(frozen=True)
class Observation:
    internal: CheckResult | None
    external: CheckResult | None
    is_external_known: bool  # False면 external은 무시 (워커 결과 미수신)


@dataclass(frozen=True)
class ServiceState:
    status: str  # up | degraded | down | unknown
    consecutive_failures: int
    consecutive_successes: int
    cause: str | None  # down일 때만 값 있음
    since: datetime | None  # down: 첫 실패 시각, 실패 연속 중인 up/degraded: 첫 실패 시각, 그 외: 현재 상태 진입 시각
    last_notified_at: datetime | None  # 알림 계획기 소유 (advance는 그대로 전달)
    is_down_notified: bool  # 알림 계획기 소유 (down 이탈 시에만 False로 초기화)


@dataclass(frozen=True)
class Transition:
    service_id: str
    before: str
    after: str
    cause: str | None
    since: datetime  # down 전이: 첫 실패 시각, 복구 전이: 장애 시작 시각, 그 외: 전이 시각


INITIAL_STATE = ServiceState(STATUS_UNKNOWN, 0, 0, None, None, None, False)


def advance(service_id: str, previous: ServiceState, observation: Observation,
            policy: AlertPolicy, now: datetime) -> tuple[ServiceState, Transition | None]:
    """관측 1건 반영: 데이터 없음 유지 > 실패 연속 판정 > 성공 연속 판정"""
    checks = _effective_checks(observation)
    if not checks:
        return previous, None
    if any(not check.is_ok for check in checks):
        return _advance_on_failure(service_id, previous, observation, policy, now)
    # 외부 원인 down은 확인된 외부 성공만 복구로 인정 (내부만 정상인 틱은 데이터 없음)
    if _is_external_cause_down(previous) and not _has_known_external_result(observation):
        return previous, None
    is_slow = any(check.is_slow for check in checks)
    return _advance_on_success(service_id, previous, is_slow, policy, now)


def _effective_checks(observation: Observation) -> list[CheckResult]:
    """판정에 쓰는 결과만 수집 (외부는 결과 확인된 경우만)"""
    checks = []
    if observation.internal is not None:
        checks.append(observation.internal)
    if observation.is_external_known and observation.external is not None:
        checks.append(observation.external)
    return checks


def _is_external_cause_down(state: ServiceState) -> bool:
    """down이며 원인이 외부 경로·도달 불가인지"""
    return state.status == STATUS_DOWN and state.cause in (CAUSE_EXTERNAL_PATH, CAUSE_UNREACHABLE)


def _has_known_external_result(observation: Observation) -> bool:
    """외부 결과가 확인된 관측인지"""
    return observation.is_external_known and observation.external is not None


def _decide_cause(observation: Observation) -> str:
    """실패 원인: 내부 실패 > service_down, 내부 정상 > external_path, 내부 없음 > unreachable"""
    if observation.internal is None:
        return CAUSE_UNREACHABLE
    if not observation.internal.is_ok:
        return CAUSE_SERVICE_DOWN
    return CAUSE_EXTERNAL_PATH


def _advance_on_failure(service_id: str, previous: ServiceState, observation: Observation,
                        policy: AlertPolicy, now: datetime) -> tuple[ServiceState, Transition | None]:
    """실패 틱 반영: 실패 연속 증가 > 첫 실패 시각 기록 > 기준 도달 시 down 전이"""
    failure_count = previous.consecutive_failures + 1
    cause = _decide_cause(observation)

    # 이미 down (원인만 갱신, 전이 없음)
    if previous.status == STATUS_DOWN:
        return replace(previous, consecutive_failures=failure_count, consecutive_successes=0, cause=cause), None

    # 실패 연속의 첫 틱에서 시작 시각 기록
    first_failure_at = now if previous.consecutive_failures == 0 else (previous.since or now)
    state = replace(previous, consecutive_failures=failure_count, consecutive_successes=0,
                    cause=None, since=first_failure_at)
    if failure_count < policy.failures_to_down:
        return state, None

    down_state = replace(state, status=STATUS_DOWN, cause=cause)
    return down_state, Transition(service_id, previous.status, STATUS_DOWN, cause, first_failure_at)


def _advance_on_success(service_id: str, previous: ServiceState, is_slow: bool,
                        policy: AlertPolicy, now: datetime) -> tuple[ServiceState, Transition | None]:
    """성공 틱 반영: 성공 연속 증가 > down 복구·최초 관측·up/degraded 전환 판정"""
    success_count = previous.consecutive_successes + 1
    target_status = STATUS_DEGRADED if is_slow else STATUS_UP
    state = replace(previous, consecutive_failures=0, consecutive_successes=success_count)

    # down 복구 (연속 성공 기준 충족 시, 알림 플래그 초기화)
    if previous.status == STATUS_DOWN:
        if success_count < policy.successes_to_up:
            return state, None
        recovered = replace(state, status=target_status, cause=None, since=now, is_down_notified=False)
        return recovered, Transition(service_id, STATUS_DOWN, target_status, previous.cause, previous.since or now)

    # 최초 관측 (전이 아님)
    if previous.status == STATUS_UNKNOWN:
        return replace(state, status=target_status, cause=None, since=now), None

    # up <-> degraded
    if target_status != previous.status:
        return (replace(state, status=target_status, cause=None, since=now),
                Transition(service_id, previous.status, target_status, None, now))

    # 같은 상태 유지 (실패 연속이 끊긴 경우 since 재설정)
    since = now if previous.consecutive_failures > 0 else previous.since
    return replace(state, cause=None, since=since), None
