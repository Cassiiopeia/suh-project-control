"""관제소 폴러: 1분 틱으로 등록 파일·점검 창·심박·내부 점검·상태 전이·알림·저장·장애 구간·일일 요약·보관 정리 연결
저장소는 폴러 스레드에서만 사용 (내부 점검 스레드는 결과만 반환), 틱 예외는 삼켜서 스레드 생존
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Callable, Mapping

from config.control_tower_config import POLL_INTERVAL_SECONDS
from service.control_tower.alert_planner import Notification, plan_notifications
from service.control_tower.check_runner import run_check, utc_now
from service.control_tower.digest import build_daily_digest
from service.control_tower.meta_keys import (
    META_KEY_LAST_DIGEST_DAY, META_KEY_LAST_PURGE_DAY, META_KEY_REGISTRY_ERROR,
)
from service.control_tower.poller_heartbeat import HeartbeatStep
from service.control_tower.poller_snapshot import EMPTY_VIEW, PollerSnapshot, PublishedView
from service.control_tower.poller_steps import (
    build_observations, carry_over_external_observations, is_under_maintenance, merge_maintenance,
    monitored_services, restore_undelivered_alert_flags, run_internal_checks,
)
from service.control_tower.registry import MaintenanceWindow, Registry, RegistryError, load_registry
from service.control_tower.registry_overrides import apply_overrides
from service.control_tower.state_machine import (
    INITIAL_STATE, STATUS_DOWN, Observation, ServiceState, Transition, advance,
)
from service.control_tower.system_alerts import (
    ConditionAlert, build_registry_error_alert, build_registry_recovered_notice,
)
from service.control_tower.time_zones import KST

logger = logging.getLogger(__name__)

# 등록 파일을 한 번도 읽지 못했을 때 라우터에 주는 빈 등록 정보
EMPTY_REGISTRY = Registry(projects=(), services=())


class ControlTowerPoller:
    def __init__(self, registry_path: str, store, dispatcher, heartbeat_client, check_runner=run_check,
                 now=utc_now, interval_seconds: float = POLL_INTERVAL_SECONDS,
                 environ: Mapping[str, str] | None = None, invite_attribution=None):
        self._registry_path = registry_path
        self._invite_attribution = invite_attribution  # InviteAttributionStep (디스코드 미설정이면 None)
        self._store = store
        self._dispatcher = dispatcher
        self._heartbeat_step = HeartbeatStep(heartbeat_client, store, dispatcher)
        self._check_runner = check_runner
        self._now = now
        self._interval_seconds = interval_seconds
        self._environ = environ if environ is not None else os.environ
        self._registry: Registry | None = None  # 실효 등록 정보 (등록 파일 + 관리자 화면 덮어쓰기)
        self._file_registry: Registry | None = None  # 덮어쓰기 전 등록 파일 그대로 (관리 API 원본 비교용)
        self._recorded_registry_error: str | None = None  # None: 아직 meta 기록 전
        self._registry_error_alert: ConditionAlert | None = None  # 첫 재로드 때 meta 값으로 생성
        self._states: dict[str, ServiceState] | None = None  # 첫 틱에 저장소에서 1회 복원
        self._stop_event = threading.Event()
        # 틱 끝에 통째로 교체하는 불변 뷰 (요청 스레드는 참조 하나만 읽음)
        self._published_view = EMPTY_VIEW

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run_loop, daemon=True, name="control-tower-poller")
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop_event.set()

    def current_registry(self) -> Registry:
        """마지막으로 읽은 등록 정보 (없으면 빈 등록 정보)"""
        return self._registry or EMPTY_REGISTRY

    def current_file_registry(self) -> Registry:
        """마지막으로 읽은 등록 파일 원본 (없으면 빈 등록 정보)"""
        return self._file_registry or EMPTY_REGISTRY

    def current_states(self) -> dict[str, ServiceState]:
        return dict(self._states or {})

    def snapshot(self) -> PollerSnapshot:
        """관리자 화면용 현재 상태: 등록 정보·상태·서비스별 마지막 관측·마지막 틱 시각 (불변)"""
        view = self._published_view
        return PollerSnapshot(self._registry, view.states, view.observations, view.last_tick_at)

    def tick(self) -> None:
        """틱 1회: 등록 파일 > 점검 창 > 심박 > 내부 점검 > 상태 전이 > 알림 계획·발송 > 장애 구간·저장 > 요약 > 정리 > 초대 귀속"""
        now = self._now()
        registry = self._reload_registry(now)
        if registry is None:
            return
        previous_states = self._load_states_once()

        # 점검 창 (등록 파일 + 관리자 화면, 같은 서비스는 관리자 화면 우선): 알림·Worker 스냅샷·공개 장애 공용
        maintenance = merge_maintenance(registry, self._store.active_maintenance(now))

        # 관측 조립 (심박 > 내부 점검 병렬)
        services = monitored_services(registry)
        heartbeat = self._heartbeat_step.run(registry, maintenance, now)
        internal_results = run_internal_checks(services, self._check_runner, registry.alert.slow_milliseconds)
        observations = build_observations(services, internal_results, heartbeat.external_results,
                                          heartbeat.home_network_check)

        # 상태 전이 > 알림 > 발송 실패한 down 알림은 다음 틱 재계획
        advanced_states, transitions = self._advance_states(registry, previous_states, observations, now)
        notifications, planned_states = plan_notifications(registry, advanced_states, transitions, maintenance, now)
        undelivered = [notification for notification in notifications if not self._dispatch_safely(notification)]
        if undelivered and self._dispatcher.is_delivery_configured():
            planned_states = restore_undelivered_alert_flags(undelivered, advanced_states, planned_states)

        # 장애 구간 > 저장 (서비스별 독립) > 하루 1회 작업
        self._states = planned_states
        self._publish_view(planned_states, observations, now)
        self._record_incidents(transitions, maintenance, now)
        self._save_tick(observations, previous_states, planned_states, now)
        self._run_daily_task("digest", lambda: self._send_digest_if_due(registry, now))
        self._run_daily_task("purge", lambda: self._purge_if_due(now))
        # 초대 귀속: 예외 없음 (실패는 단계 안에서 로그)
        if self._invite_attribution is not None:
            self._invite_attribution.run(now)

    def _publish_view(self, states: dict[str, ServiceState], observations: dict[str, Observation],
                      now: datetime) -> None:
        """snapshot용 불변 뷰 교체 (외부 결과는 직전 값 이월)"""
        displayed_observations = carry_over_external_observations(
            observations, self._published_view.observations, now)
        self._published_view = PublishedView(
            MappingProxyType(dict(states)), MappingProxyType(displayed_observations), now)

    def _run_loop(self) -> None:
        """고정 주기: 틱 소요 시간을 빼고 대기"""
        while not self._stop_event.is_set():
            started_seconds = time.monotonic()
            try:
                self.tick()
            except Exception:  # 틱 단위로 삼켜서 스레드 생존
                logger.exception("[control-tower poller] tick failed")
            elapsed_seconds = time.monotonic() - started_seconds
            self._stop_event.wait(max(0.0, self._interval_seconds - elapsed_seconds))

    def _reload_registry(self, now: datetime) -> Registry | None:
        """등록 파일 재로드 > 덮어쓰기 적용: 성공 > 교체, 실패 > 이전 등록 정보 유지 + 오류 종류별 로그·전역 알림 1회 (해소 시 정상화 1회)"""
        error_alert = self._registry_alert()  # meta 갱신 전에 직전 오류 읽기
        try:
            file_registry = load_registry(self._registry_path, self._environ)
            registry = apply_overrides(file_registry, self._store)
        except Exception as error:
            error_text = _summarize_registry_error(error)
            if error_text != self._recorded_registry_error:
                logger.warning("[control-tower poller] registry reload failed : %s", error_text)
            self._record_registry_error(error_text)
            error_alert.report(error_text, now, _first_registry_problem(error))
            return self._registry
        if self._recorded_registry_error:
            logger.info("[control-tower poller] registry reloaded after error")
        self._file_registry = file_registry
        self._registry = registry
        self._record_registry_error("")
        error_alert.report(None, now)
        return registry

    def _registry_alert(self) -> ConditionAlert:
        """등록 파일 오류 알림 (재기동 전 기록된 같은 오류는 다시 알리지 않음)"""
        if self._registry_error_alert is None:
            previous_error = self._store.get_meta(META_KEY_REGISTRY_ERROR) or None
            self._registry_error_alert = ConditionAlert(
                self._dispatcher, build_registry_error_alert, build_registry_recovered_notice, previous_error)
        return self._registry_error_alert

    def _record_registry_error(self, error_text: str) -> None:
        """meta registry_error 기록 (값이 바뀔 때만)"""
        if error_text != self._recorded_registry_error:
            self._store.set_meta(META_KEY_REGISTRY_ERROR, error_text)
            self._recorded_registry_error = error_text

    def _load_states_once(self) -> dict[str, ServiceState]:
        """서비스 상태 복원 (재기동 후 첫 틱 1회, Review Focus 1)"""
        if self._states is None:
            self._states = self._store.load_states()
        return self._states

    @staticmethod
    def _advance_states(registry: Registry, previous_states: dict[str, ServiceState],
                        observations: dict[str, Observation],
                        now: datetime) -> tuple[dict[str, ServiceState], list[Transition]]:
        """관측별 상태 전이 (저장 상태 없으면 초기 상태, 첫 관측 전 초기 상태는 보관 안 함)"""
        states = dict(previous_states)
        transitions: list[Transition] = []
        for service_id, observation in observations.items():
            previous = previous_states.get(service_id, INITIAL_STATE)
            state, transition = advance(service_id, previous, observation, registry.alert, now)
            if service_id in previous_states or state != INITIAL_STATE:
                states[service_id] = state
            if transition is not None:
                transitions.append(transition)
        return states, transitions

    def _dispatch_safely(self, notification: Notification) -> bool:
        """알림 1건 발송 > 성공 여부 (예외는 기록 후 실패, 나머지 발송 계속)"""
        try:
            return self._dispatcher.dispatch(notification) is True
        except Exception as error:
            logger.warning("[control-tower poller] dispatch failed : kind %s : %s",
                           notification.kind, type(error).__name__)
            return False

    def _record_incidents(self, transitions: list[Transition], maintenance: dict[str, MaintenanceWindow],
                          now: datetime) -> None:
        """장애 구간: down 진입 > 열기(첫 실패 시각), down 이탈 > 닫기(지금), 점검 창 안 여부 함께 기록, 서비스별 독립"""
        for transition in transitions:
            is_in_maintenance = is_under_maintenance(maintenance, transition.service_id, now)
            if transition.after == STATUS_DOWN:
                self._persist(transition.service_id, lambda: self._store.open_incident(
                    transition.service_id, transition.cause, transition.since, is_in_maintenance=is_in_maintenance))
            elif transition.before == STATUS_DOWN:
                self._persist(transition.service_id, lambda: self._store.close_incident(
                    transition.service_id, now, is_in_maintenance=is_in_maintenance))

    def _save_tick(self, observations: dict[str, Observation], previous_states: dict[str, ServiceState],
                   planned_states: dict[str, ServiceState], now: datetime) -> None:
        """점검 결과 저장 + 바뀐 상태만 저장 (서비스별 독립)"""
        for service_id, observation in observations.items():
            self._persist(service_id, lambda: self._store.save_results(service_id, observation, now))
        for service_id, state in planned_states.items():
            if previous_states.get(service_id) != state:
                self._persist(service_id, lambda: self._store.save_state(service_id, state))

    @staticmethod
    def _persist(service_id: str, write: Callable[[], object]) -> None:
        """서비스 1건 기록 (실패는 로그만, 나머지 기록 계속)"""
        try:
            write()
        except Exception as error:
            logger.warning("[control-tower poller] persist failed : %s %s", service_id, type(error).__name__)

    @staticmethod
    def _run_daily_task(task_name: str, task: Callable[[], None]) -> None:
        """하루 1회 작업 실행 (실패는 로그만, 다음 틱 재시도)"""
        try:
            task()
        except Exception as error:
            logger.warning("[control-tower poller] daily task failed : %s %s", task_name, type(error).__name__)

    def _send_digest_if_due(self, registry: Registry, now: datetime) -> None:
        """요약 시각(KST) 이후 하루 1회: 전날 요약 발송 (발송 실패해도 그날은 재시도 안 함)"""
        now_kst = now.astimezone(KST)
        today_text = now_kst.date().isoformat()
        if now_kst.hour < registry.alert.digest_hour_kst:
            return
        if self._store.get_meta(META_KEY_LAST_DIGEST_DAY) == today_text:
            return
        digest = build_daily_digest(registry, self._store, now_kst.date() - timedelta(days=1))
        self._store.set_meta(META_KEY_LAST_DIGEST_DAY, today_text)
        self._dispatch_safely(digest)

    def _purge_if_due(self, now: datetime) -> None:
        """KST 하루 1회 보관 기간 초과 데이터 삭제"""
        today_text = now.astimezone(KST).date().isoformat()
        if self._store.get_meta(META_KEY_LAST_PURGE_DAY) == today_text:
            return
        self._store.purge(now)
        self._store.set_meta(META_KEY_LAST_PURGE_DAY, today_text)


def _first_registry_problem(error: Exception) -> str:
    """알림 본문용 첫 문제 1줄 (그 외 예외는 종류 이름만)"""
    if isinstance(error, RegistryError) and error.problems:
        return error.problems[0]
    return type(error).__name__


def _summarize_registry_error(error: Exception) -> str:
    """등록 파일 오류 요약: 첫 문제 + 남은 개수 (그 외 예외는 종류 이름만)"""
    if isinstance(error, RegistryError) and error.problems:
        remaining_count = len(error.problems) - 1
        return error.problems[0] + (f" (+{remaining_count} more)" if remaining_count else "")
    return type(error).__name__
