"""관제소 자체 상태 알림: 등록 파일 오류(첫 로드·재로드, 오류 종류별 1회, 정상화 1회), 심박 거절(R31: 집 인터넷 데이터 없음, 상태별 1회)"""
from __future__ import annotations

import requests

from control_tower_poller_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    REGISTRY_YAML, FakeDispatcher, FakeHeartbeatClient, check_runner, clock, dispatcher, make_poller,
    registry_path, run_ticks, store,
)
from service.control_tower.heartbeat_client import HeartbeatRejectedError, HeartbeatResponse
from service.control_tower.poller import ControlTowerPoller
from service.control_tower.store import ControlTowerStore

REGISTRY_ERROR_TITLE = "[관제소] 등록 파일 오류"
REGISTRY_RECOVERED_TITLE = "[관제소] 등록 파일 정상화"
BROKEN_YAML = "projects: [unclosed"
# 상태값 오류 + env 값(내부 IP)을 쓰는 등록 파일: 알림 본문에 env 값이 없어야 함
INVALID_STATUS_YAML = """
infrastructure:
  - id: nas
    name: NAS
    status: sleeping
    checks:
      internal: {tcp: "${NAS_LAN_HOST}:5001"}
"""
SECRET_HOST = "10.9.8.7"


def _registry_notifications(dispatcher: FakeDispatcher):
    return [notification for notification in dispatcher.notifications if notification.title.startswith("[관제소] 등록")]


# ---------- 등록 파일 오류 ----------

def test_한_번도_읽지_못한_등록_파일은_전역_긴급_1건을_보내고_고치면_정상화_1건을_보낸다(
        tmp_path, store, dispatcher, check_runner, clock):
    path = tmp_path / "services.yml"
    path.write_text(BROKEN_YAML, encoding="utf-8")
    poller = make_poller(path, store, dispatcher, check_runner, clock)

    run_ticks(poller, clock, 3)

    assert dispatcher.titles() == [REGISTRY_ERROR_TITLE]
    alert = dispatcher.notifications[0]
    assert (alert.scope, alert.kind, alert.severity) == ("global", "alert", "critical")
    assert "invalid YAML" in alert.body.splitlines()[0]

    path.write_text(REGISTRY_YAML, encoding="utf-8")
    run_ticks(poller, clock, 3)

    assert dispatcher.titles() == [REGISTRY_ERROR_TITLE, REGISTRY_RECOVERED_TITLE]
    assert dispatcher.notifications[1].severity == "info"


def test_재로드_오류는_종류가_바뀔_때마다_1건이고_본문에_env_값이_없다(
        registry_path, store, dispatcher, check_runner, clock):
    poller = ControlTowerPoller(str(registry_path), store, dispatcher, None, check_runner=check_runner, now=clock,
                                environ={"NAS_LAN_HOST": SECRET_HOST})
    run_ticks(poller, clock, 1)

    registry_path.write_text(BROKEN_YAML, encoding="utf-8")
    run_ticks(poller, clock, 2)
    registry_path.write_text(INVALID_STATUS_YAML, encoding="utf-8")
    run_ticks(poller, clock, 2)

    alerts = _registry_notifications(dispatcher)
    assert [alert.title for alert in alerts] == [REGISTRY_ERROR_TITLE, REGISTRY_ERROR_TITLE]
    assert "sleeping" in alerts[1].body
    assert all(SECRET_HOST not in alert.body for alert in alerts)


def test_재기동_후_같은_오류는_다시_알리지_않는다(tmp_path, store, dispatcher, check_runner, clock):
    path = tmp_path / "services.yml"
    path.write_text(BROKEN_YAML, encoding="utf-8")
    run_ticks(make_poller(path, store, dispatcher, check_runner, clock), clock, 1)

    restarted_store = ControlTowerStore(store._path)
    restarted_dispatcher = FakeDispatcher()
    run_ticks(make_poller(path, restarted_store, restarted_dispatcher, check_runner, clock), clock, 2)

    assert dispatcher.titles() == [REGISTRY_ERROR_TITLE]
    assert restarted_dispatcher.notifications == []
    restarted_store.close()


def test_등록_파일_오류_알림_발송_실패는_다음_틱에_재시도하고_디스코드_미설정이면_재시도_안_한다(
        tmp_path, store, check_runner, clock):
    path = tmp_path / "services.yml"
    path.write_text(BROKEN_YAML, encoding="utf-8")
    flaky_dispatcher = FakeDispatcher(undelivered_counts={REGISTRY_ERROR_TITLE: 1})
    run_ticks(make_poller(path, store, flaky_dispatcher, check_runner, clock), clock, 3)
    assert flaky_dispatcher.titles() == [REGISTRY_ERROR_TITLE, REGISTRY_ERROR_TITLE]

    other_path = tmp_path / "other.yml"
    other_path.write_text("projects: {", encoding="utf-8")
    unconfigured_dispatcher = FakeDispatcher(is_configured=False)
    run_ticks(make_poller(other_path, store, unconfigured_dispatcher, check_runner, clock), clock, 3)
    assert unconfigured_dispatcher.titles() == [REGISTRY_ERROR_TITLE]


# ---------- 심박 거절 (R31) ----------

def _heartbeat_sequence(*outcomes) -> FakeHeartbeatClient:
    """틱마다 순서대로: 'ok' 성공, 'down' 연결 실패, 그 외 문자열 거절 상태, 예외 객체 raise (마지막 값 반복)"""
    def factory(now):
        index = min(len(client.calls) - 1, len(outcomes) - 1)
        outcome = outcomes[index]
        if outcome == "ok":
            return HeartbeatResponse({}, now)
        if outcome == "down":
            return None
        if isinstance(outcome, Exception):
            return outcome
        return HeartbeatRejectedError(outcome)
    client = FakeHeartbeatClient(factory)  # factory가 호출 횟수를 읽도록 먼저 생성
    return client


def test_심박_거절은_집_인터넷_실패로_세지_않고_전역_긴급_1건만_보낸다(registry_path, store, dispatcher, check_runner, clock):
    heartbeat_client = _heartbeat_sequence("401")
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client)

    run_ticks(poller, clock, 5)

    assert "home-network" not in store.load_states()
    assert dispatcher.titles() == ["[관제소] Worker 심박 거절 (401)"]
    alert = dispatcher.notifications[0]
    assert (alert.scope, alert.kind, alert.severity) == ("global", "alert", "critical")
    assert store.get_meta("heartbeat_is_ok") == "0"


def test_거절_상태가_바뀌면_다시_알리고_심박이_성공하면_정상화_1건(registry_path, store, dispatcher, check_runner, clock):
    heartbeat_client = _heartbeat_sequence("401", "401", "500", "500", "ok")
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client)

    run_ticks(poller, clock, 7)

    assert dispatcher.titles() == [
        "[관제소] Worker 심박 거절 (401)", "[관제소] Worker 심박 거절 (500)", "[관제소] Worker 심박 정상화"]
    assert dispatcher.notifications[-1].severity == "info"
    assert store.load_states()["home-network"].status == "up"


def test_연결_실패는_거절_알림_없이_집_인터넷_실패로_센다(registry_path, store, dispatcher, check_runner, clock):
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock, _heartbeat_sequence("down"))

    run_ticks(poller, clock, 3)

    assert dispatcher.titles() == ["[다운] 집 인터넷"]


def test_심박_코드_예외는_데이터_없음이고_알림이_없다(registry_path, store, dispatcher, check_runner, clock):
    heartbeat_client = _heartbeat_sequence(requests.exceptions.InvalidURL("bad"))
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client)

    run_ticks(poller, clock, 4)

    assert "home-network" not in store.load_states()
    assert dispatcher.notifications == []
    assert store.get_meta("heartbeat_is_ok") == "0"
