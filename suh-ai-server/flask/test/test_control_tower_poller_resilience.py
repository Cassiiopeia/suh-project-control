"""관제소 폴러 장애 내성: 발송 실패 재시도(디스코드 미설정 제외), 같은 Worker 결과 중복 반영 방지,
서비스별 독립 저장, 공개 장애 조회 실패, 점검 창 병합, 고정 주기 대기"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from control_tower_poller_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    BASE_TIME, CANARY_TARGET, NAS_TARGET, FakeDispatcher, FakeHeartbeatClient, check_runner, clock, dispatcher,
    make_poller, registry_path, run_ticks, store,
)
from service.control_tower import poller as poller_module
from service.control_tower.check_runner import CheckResult
from service.control_tower.heartbeat_client import HeartbeatResponse
from service.control_tower.poller_steps import fresh_external_results, merge_maintenance
from service.control_tower.registry import MaintenanceWindow, Registry

NAS_DOWN_TITLE = "[다운] 시놀로지 NAS"
NAS_RECOVERED_TITLE = "[복구] 시놀로지 NAS"


def test_발송_실패한_down_알림은_다음_틱에_다시_보내고_성공하면_멈춘다(registry_path, store, check_runner, clock):
    flaky_dispatcher = FakeDispatcher(undelivered_counts={NAS_DOWN_TITLE: 2})
    check_runner.is_ok_by_target[NAS_TARGET] = False

    run_ticks(make_poller(registry_path, store, flaky_dispatcher, check_runner, clock), clock, 8)

    assert flaky_dispatcher.titles() == [NAS_DOWN_TITLE] * 3
    assert store.load_states()["nas"].is_down_notified


def test_발송_예외도_매_틱_재시도하고_알림_완료로_기록하지_않는다(registry_path, store, check_runner, clock):
    exploding_dispatcher = FakeDispatcher(failing_titles=(NAS_DOWN_TITLE,))
    check_runner.is_ok_by_target[NAS_TARGET] = False

    run_ticks(make_poller(registry_path, store, exploding_dispatcher, check_runner, clock), clock, 5)

    assert exploding_dispatcher.titles() == [NAS_DOWN_TITLE] * 3
    nas_state = store.load_states()["nas"]
    assert not nas_state.is_down_notified and nas_state.last_notified_at is None


def test_디스코드가_미설정이면_실패한_알림을_재시도하지_않는다(registry_path, store, check_runner, clock):
    unconfigured_dispatcher = FakeDispatcher(is_configured=False)
    check_runner.is_ok_by_target[NAS_TARGET] = False

    run_ticks(make_poller(registry_path, store, unconfigured_dispatcher, check_runner, clock), clock, 8)

    assert unconfigured_dispatcher.titles() == [NAS_DOWN_TITLE]


def test_복구_알림_발송_실패는_재시도하지_않는다(registry_path, store, check_runner, clock):
    flaky_dispatcher = FakeDispatcher(undelivered_counts={NAS_RECOVERED_TITLE: 5})
    check_runner.is_ok_by_target[NAS_TARGET] = False
    poller = make_poller(registry_path, store, flaky_dispatcher, check_runner, clock)
    run_ticks(poller, clock, 3)

    check_runner.is_ok_by_target[NAS_TARGET] = True
    run_ticks(poller, clock, 5)

    assert flaky_dispatcher.titles() == [NAS_DOWN_TITLE, NAS_RECOVERED_TITLE]


def test_같은_checked_at의_Worker_결과가_반복되면_한_번만_반영한다(registry_path, store, dispatcher, check_runner, clock):
    checked_at = BASE_TIME - timedelta(seconds=10)
    repeated = HeartbeatResponse({"elum-api": CheckResult(False, False, 503, 40, None, checked_at)}, checked_at)
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock,
                         FakeHeartbeatClient(lambda now: repeated))

    run_ticks(poller, clock, 3)

    elum_state = store.load_states()["elum-api"]
    assert elum_state.status != "down" and elum_state.consecutive_failures == 1
    assert dispatcher.notifications == []
    assert [(total, ok) for _, total, ok in store.uptime_by_day("elum-api", 1)] == [(1, 0)]


def test_이미_반영한_시각보다_오래된_Worker_결과는_버린다():
    applied_at = BASE_TIME - timedelta(seconds=30)
    older_at = BASE_TIME - timedelta(seconds=90)
    newer_at = BASE_TIME - timedelta(seconds=10)

    def response(checked_at):
        return HeartbeatResponse({"elum-api": CheckResult(False, False, 503, 40, None, checked_at)}, checked_at)

    assert fresh_external_results(response(older_at), BASE_TIME, applied_at) == {}
    assert fresh_external_results(response(applied_at), BASE_TIME, applied_at) == {}
    assert list(fresh_external_results(response(newer_at), BASE_TIME, applied_at)) == ["elum-api"]
    assert list(fresh_external_results(response(older_at), BASE_TIME, None)) == ["elum-api"]


def test_한_서비스의_기록_실패가_다른_기록과_하루_작업을_막지_않는다(
        registry_path, store, dispatcher, check_runner, clock, monkeypatch, caplog):
    original_save_results = store.save_results
    original_open_incident = store.open_incident

    def save_results_failing_for_nas(service_id, observation, now):
        if service_id == "nas":
            raise sqlite3.OperationalError("database is locked")
        original_save_results(service_id, observation, now)

    def open_incident_failing_for_nas(service_id, cause, started_at, **options):
        if service_id == "nas":
            raise sqlite3.OperationalError("database is locked")
        return original_open_incident(service_id, cause, started_at, **options)

    monkeypatch.setattr(store, "save_results", save_results_failing_for_nas)
    monkeypatch.setattr(store, "open_incident", open_incident_failing_for_nas)
    check_runner.is_ok_by_target[NAS_TARGET] = False
    check_runner.is_ok_by_target[CANARY_TARGET] = False

    with caplog.at_level(logging.WARNING):
        run_ticks(make_poller(registry_path, store, dispatcher, check_runner, clock), clock, 3)

    states = store.load_states()
    assert states["nas"].status == "down" and states["control-tower-canary"].status == "down"
    assert [incident["service_id"] for incident in store.recent_incidents(10, BASE_TIME)] == ["control-tower-canary"]
    assert store.uptime_by_day("control-tower-canary", 1)[0][1] == 3
    assert store.get_meta("last_purge_day") == "2026-11-06"
    assert "[control-tower poller] persist failed : nas OperationalError" in caplog.text


def test_공개_장애_조회_실패는_심박_실패로_세지_않고_빈_목록을_보낸다(
        registry_path, store, dispatcher, check_runner, clock, monkeypatch):
    def failing_recent_incidents(limit, since):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "recent_incidents", failing_recent_incidents)
    heartbeat_client = FakeHeartbeatClient()

    run_ticks(make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client), clock, 1)

    assert heartbeat_client.calls[0][1] == []
    assert store.get_meta("heartbeat_is_ok") == "1"


def test_점검_창_병합은_같은_서비스면_관리자_화면_값이_이긴다():
    registry_until = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
    stored_until = datetime(2026, 11, 6, 5, 0, tzinfo=timezone.utc)
    registry = Registry(projects=(), services=(), maintenance=(
        MaintenanceWindow("nas", registry_until, "등록 파일"), MaintenanceWindow("elum-api", registry_until, "등록 파일")))

    merged = merge_maintenance(registry, {"nas": MaintenanceWindow("nas", stored_until, "관리자 화면")})

    assert merged["nas"].until == stored_until and merged["nas"].reason == "관리자 화면"
    assert merged["elum-api"].until == registry_until


def test_관리자_화면_점검_창이면_NAS_down_알림이_없다(registry_path, store, dispatcher, check_runner, clock):
    store.set_maintenance("nas", BASE_TIME + timedelta(hours=1), "업데이트")
    check_runner.is_ok_by_target[NAS_TARGET] = False

    run_ticks(make_poller(registry_path, store, dispatcher, check_runner, clock), clock, 5)

    assert dispatcher.notifications == []
    assert store.load_states()["nas"].status == "down"


class RecordingStopEvent:
    """wait 호출 대기 시간 기록 후 정지"""

    def __init__(self):
        self.wait_seconds: list[float] = []
        self.is_stopped = False

    def is_set(self) -> bool:
        return self.is_stopped

    def wait(self, seconds: float) -> None:
        self.wait_seconds.append(seconds)
        self.is_stopped = True


def test_루프는_틱_소요_시간을_뺀_만큼만_기다린다(registry_path, store, dispatcher, check_runner, clock, monkeypatch):
    poller = poller_module.ControlTowerPoller(str(registry_path), store, dispatcher, None, check_runner=check_runner,
                                              now=clock, interval_seconds=1.0, environ={})
    stop_event = RecordingStopEvent()
    poller._stop_event = stop_event
    poller.tick = lambda: None
    monotonic_values = iter([100.0, 100.4])
    monkeypatch.setattr(poller_module.time, "monotonic", lambda: next(monotonic_values))

    poller._run_loop()

    assert len(stop_event.wait_seconds) == 1 and abs(stop_event.wait_seconds[0] - 0.6) < 1e-9


def test_틱마다_초대_귀속_단계를_틱_시작_시각으로_1회_실행한다(registry_path, store, dispatcher, check_runner, clock):
    class RecordingInviteStep:
        def __init__(self):
            self.run_times: list[datetime] = []

        def run(self, now: datetime) -> None:
            self.run_times.append(now)

    invite_step = RecordingInviteStep()
    poller = poller_module.ControlTowerPoller(str(registry_path), store, dispatcher, None, check_runner=check_runner,
                                              now=clock, environ={}, invite_attribution=invite_step)
    run_ticks(poller, clock, 2)

    assert len(invite_step.run_times) == 2 and invite_step.run_times[0] < invite_step.run_times[1]
