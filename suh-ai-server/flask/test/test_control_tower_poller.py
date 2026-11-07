"""관제소 폴러 틱: down 알림 1건, 등록 파일 오류 시 이전 설정 유지, 재기동 중복 방지, 심박·외부 결과, 요약·정리 하루 1회"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import pytest

from service.control_tower.check_runner import CheckResult
from service.control_tower.heartbeat_client import HeartbeatResponse
from service.control_tower.poller import ControlTowerPoller
from service.control_tower.store import ControlTowerStore

BASE_TIME = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)  # KST 11-06 03:00 (요약 시각 전)
NAS_TARGET = "nas.local:5001"
CANARY_TARGET = "http://127.0.0.1:18080/"

REGISTRY_YAML = """
alert:
  failures_to_down: 3
  successes_to_up: 2
infrastructure:
  - id: nas
    name: 시놀로지 NAS
    checks:
      internal: {tcp: "nas.local:5001"}
  - id: windows
    name: Windows SUH AI 서버
  - id: home-network
    name: 집 인터넷
projects:
  - id: elum
    name: 이룸
    services:
      - id: elum-api
        name: 이룸 API
        public: true
        depends_on: nas
        checks:
          external: {url: "https://api.elum.example.com/healthz", expect: [200]}
      - id: elum-admin
        name: 이룸 관리자
        public: false
        depends_on: nas
        checks:
          external: {url: "https://admin.elum.example.com/"}
      - id: elum-old
        name: 이룸 구버전
        status: retired
        checks:
          internal: {url: "http://127.0.0.1:18081/"}
      - id: control-tower-canary
        name: 카나리아
        checks:
          internal: {url: "http://127.0.0.1:18080/"}
"""


class FakeClock:
    def __init__(self, moment: datetime = BASE_TIME):
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, minutes: int = 1) -> None:
        self.moment += timedelta(minutes=minutes)


class FakeCheckRunner:
    """target별 정상 여부 (기본 정상), 호출된 target 기록"""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.is_ok_by_target: dict[str, bool] = {}
        self.called_targets: list[str] = []

    def __call__(self, spec, slow_milliseconds):
        self.called_targets.append(spec.target)
        is_ok = self.is_ok_by_target.get(spec.target, True)
        return CheckResult(is_ok, False, None, 5, None if is_ok else "connection_error", self.clock())


class FakeDispatcher:
    def __init__(self, failing_titles: tuple[str, ...] = ()):
        self.notifications = []
        self.failing_titles = failing_titles

    def dispatch(self, notification) -> bool:
        self.notifications.append(notification)
        if notification.title in self.failing_titles:
            raise RuntimeError("discord exploded")
        return True

    def titles(self) -> list[str]:
        return [notification.title for notification in self.notifications]


class FakeHeartbeatClient:
    """매 호출 response_factory(now) 반환 (None이면 실패), 호출 기록"""

    def __init__(self, response_factory=lambda now: HeartbeatResponse({}, now)):
        self.response_factory = response_factory
        self.calls: list[tuple] = []

    def send(self, registry, public_incidents, now):
        self.calls.append((registry, public_incidents, now))
        return self.response_factory(now)


@pytest.fixture
def registry_path(tmp_path):
    path = tmp_path / "services.yml"
    path.write_text(REGISTRY_YAML, encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def check_runner(clock):
    return FakeCheckRunner(clock)


@pytest.fixture
def dispatcher():
    return FakeDispatcher()


def _poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client=None):
    return ControlTowerPoller(str(registry_path), store, dispatcher, heartbeat_client,
                              check_runner=check_runner, now=clock, environ={})


def _run_ticks(poller: ControlTowerPoller, clock: FakeClock, count: int) -> None:
    for _ in range(count):
        poller.tick()
        clock.advance()


def test_NAS가_3틱_연속_실패하면_down_알림은_정확히_1건이고_장애가_열린다(
        registry_path, store, dispatcher, check_runner, clock):
    check_runner.is_ok_by_target[NAS_TARGET] = False
    poller = _poller(registry_path, store, dispatcher, check_runner, clock)

    _run_ticks(poller, clock, 2)
    assert dispatcher.notifications == []
    _run_ticks(poller, clock, 3)

    assert dispatcher.titles() == ["[다운] 시놀로지 NAS"]
    assert store.load_states()["nas"].status == "down"
    open_incidents = [incident for incident in store.recent_incidents(10, BASE_TIME) if incident["ended_at"] is None]
    assert [(incident["service_id"], incident["started_at"]) for incident in open_incidents] == [("nas", BASE_TIME)]


def test_복구되면_복구_알림_후_장애가_닫힌다(registry_path, store, dispatcher, check_runner, clock):
    check_runner.is_ok_by_target[NAS_TARGET] = False
    poller = _poller(registry_path, store, dispatcher, check_runner, clock)
    _run_ticks(poller, clock, 3)

    check_runner.is_ok_by_target[NAS_TARGET] = True
    _run_ticks(poller, clock, 2)

    assert dispatcher.titles() == ["[다운] 시놀로지 NAS", "[복구] 시놀로지 NAS"]
    incidents = store.recent_incidents(10, BASE_TIME)
    assert len(incidents) == 1 and incidents[0]["ended_at"] is not None


def test_재기동한_폴러는_이미_알린_down을_다시_알리지_않는다(
        registry_path, store, dispatcher, check_runner, clock, tmp_path):
    check_runner.is_ok_by_target[NAS_TARGET] = False
    _run_ticks(_poller(registry_path, store, dispatcher, check_runner, clock), clock, 3)
    assert len(dispatcher.notifications) == 1

    # 같은 DB 파일을 새 저장소·새 폴러로 열기 (프로세스 재기동)
    restarted_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    restarted_dispatcher = FakeDispatcher()
    restarted_poller = _poller(registry_path, restarted_store, restarted_dispatcher, check_runner, clock)
    _run_ticks(restarted_poller, clock, 5)

    assert restarted_dispatcher.notifications == []
    restarted_store.close()


def test_등록_파일이_깨지면_이전_설정으로_계속하고_오류를_메타와_로그에_한_번_남긴다(
        registry_path, store, dispatcher, check_runner, clock, caplog):
    poller = _poller(registry_path, store, dispatcher, check_runner, clock)
    _run_ticks(poller, clock, 1)
    assert store.get_meta("registry_error") == ""

    registry_path.write_text("projects: [unclosed", encoding="utf-8")
    check_runner.called_targets.clear()
    with caplog.at_level(logging.WARNING):
        _run_ticks(poller, clock, 2)

    assert check_runner.called_targets.count(NAS_TARGET) == 2  # 이전 설정으로 점검 계속
    assert "invalid YAML" in store.get_meta("registry_error")
    assert caplog.text.count("[control-tower poller] registry reload failed") == 1

    registry_path.write_text(REGISTRY_YAML, encoding="utf-8")
    _run_ticks(poller, clock, 1)
    assert store.get_meta("registry_error") == ""


def test_한_번도_읽지_못한_등록_파일이면_틱을_건너뛴다(tmp_path, store, dispatcher, check_runner, clock):
    broken_path = tmp_path / "broken.yml"
    broken_path.write_text("projects: [unclosed", encoding="utf-8")
    poller = _poller(broken_path, store, dispatcher, check_runner, clock)

    _run_ticks(poller, clock, 2)

    assert check_runner.called_targets == []
    assert "invalid YAML" in store.get_meta("registry_error")
    assert poller.current_registry().services == ()


def test_퇴역_서비스는_점검하지_않는다(registry_path, store, dispatcher, check_runner, clock):
    _run_ticks(_poller(registry_path, store, dispatcher, check_runner, clock), clock, 1)

    assert sorted(check_runner.called_targets) == sorted([NAS_TARGET, CANARY_TARGET])


def test_알림_하나의_발송_예외가_나머지_발송과_저장을_막지_않는다(registry_path, store, check_runner, clock):
    failing_dispatcher = FakeDispatcher(failing_titles=("[다운] 시놀로지 NAS",))
    check_runner.is_ok_by_target[NAS_TARGET] = False
    check_runner.is_ok_by_target[CANARY_TARGET] = False
    poller = _poller(registry_path, store, failing_dispatcher, check_runner, clock)

    _run_ticks(poller, clock, 3)

    assert sorted(failing_dispatcher.titles()) == ["[다운] 시놀로지 NAS", "[다운] 카나리아"]
    states = store.load_states()
    assert states["nas"].status == "down" and states["control-tower-canary"].status == "down"


def test_심박_설정이_없으면_집_인터넷은_데이터_없음이다(registry_path, store, dispatcher, check_runner, clock):
    _run_ticks(_poller(registry_path, store, dispatcher, check_runner, clock), clock, 3)

    assert "home-network" not in store.load_states()
    assert store.get_meta("heartbeat_is_ok") is None


def test_심박이_3틱_연속_실패하면_집_인터넷이_down이다(registry_path, store, dispatcher, check_runner, clock):
    heartbeat_client = FakeHeartbeatClient(lambda now: None)
    poller = _poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client)

    _run_ticks(poller, clock, 3)

    assert store.load_states()["home-network"].status == "down"
    assert dispatcher.titles() == ["[다운] 집 인터넷"]
    assert store.get_meta("heartbeat_is_ok") == "0"
    assert store.get_meta("heartbeat_last_ok_at") is None


def test_심박이_성공하면_마지막_성공_시각을_메타에_남긴다(registry_path, store, dispatcher, check_runner, clock):
    poller = _poller(registry_path, store, dispatcher, check_runner, clock, FakeHeartbeatClient())

    _run_ticks(poller, clock, 1)

    assert store.get_meta("heartbeat_is_ok") == "1"
    assert datetime.fromisoformat(store.get_meta("heartbeat_last_ok_at")) == BASE_TIME
    assert store.load_states()["home-network"].status == "up"


def test_신선한_외부_실패는_반영하고_3분_넘은_외부_결과는_모름으로_본다(
        registry_path, store, dispatcher, check_runner, clock):
    def failing_external(age_minutes):
        def factory(now):
            checked_at = now - timedelta(minutes=age_minutes)
            return HeartbeatResponse({"elum-api": CheckResult(False, False, 503, 40, None, checked_at)}, checked_at)
        return factory

    stale_poller = _poller(registry_path, store, dispatcher, check_runner, clock,
                           FakeHeartbeatClient(failing_external(4)))
    _run_ticks(stale_poller, clock, 3)
    assert "elum-api" not in store.load_states()

    fresh_poller = _poller(registry_path, store, dispatcher, check_runner, clock,
                           FakeHeartbeatClient(failing_external(1)))
    _run_ticks(fresh_poller, clock, 3)
    elum_state = store.load_states()["elum-api"]
    assert (elum_state.status, elum_state.cause) == ("down", "unreachable")
    assert dispatcher.titles() == ["[다운] 이룸 API"]


def test_심박에는_공개_활성_서비스의_최근_장애만_싣는다(registry_path, store, dispatcher, check_runner, clock):
    store.open_incident("elum-api", "unreachable", BASE_TIME - timedelta(days=20))  # 진행 중: 포함
    store.open_incident("elum-admin", "unreachable", BASE_TIME - timedelta(hours=1))  # 비공개: 제외
    store.open_incident("nas", "service_down", BASE_TIME - timedelta(hours=1))  # 인프라: 제외
    heartbeat_client = FakeHeartbeatClient()

    _run_ticks(_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client), clock, 1)

    _, public_incidents, _ = heartbeat_client.calls[0]
    assert public_incidents == [
        {"service_id": "elum-api", "started_at": (BASE_TIME - timedelta(days=20)).isoformat(), "ended_at": None}]


def test_일일_요약은_09시_KST_이후_하루_한_번만_보낸다(registry_path, store, dispatcher, check_runner):
    clock = FakeClock(datetime(2026, 11, 5, 23, 58, tzinfo=timezone.utc))  # KST 08:58
    poller = _poller(registry_path, store, dispatcher, check_runner, clock)

    def digest_titles():
        return [notification.title for notification in dispatcher.notifications if notification.kind == "digest"]

    _run_ticks(poller, clock, 2)  # 08:58, 08:59
    assert digest_titles() == []
    _run_ticks(poller, clock, 3)  # 09:00, 09:01, 09:02
    assert digest_titles() == ["[일일 요약] 2026-11-05"]

    clock.moment = datetime(2026, 11, 7, 0, 0, tzinfo=timezone.utc)  # 다음 날 KST 09:00
    _run_ticks(poller, clock, 2)
    assert digest_titles() == ["[일일 요약] 2026-11-05", "[일일 요약] 2026-11-06"]
    assert store.get_meta("last_digest_day") == "2026-11-07"


def test_보관_정리는_KST_하루에_한_번만_한다(registry_path, store, dispatcher, check_runner, clock, monkeypatch):
    purge_calls = []
    monkeypatch.setattr(store, "purge", lambda now: purge_calls.append(now))
    poller = _poller(registry_path, store, dispatcher, check_runner, clock)

    _run_ticks(poller, clock, 3)
    clock.advance(minutes=24 * 60)
    _run_ticks(poller, clock, 1)

    assert len(purge_calls) == 2
    assert store.get_meta("last_purge_day") == "2026-11-07"


def test_start는_데몬_스레드를_돌리고_stop으로_멈춘다(registry_path, store, dispatcher, check_runner, clock):
    poller = ControlTowerPoller(str(registry_path), store, dispatcher, None, check_runner=check_runner,
                                now=clock, interval_seconds=0.01, environ={})

    thread = poller.start()
    try:
        assert thread.daemon
        deadline_seconds = time.monotonic() + 5
        while NAS_TARGET not in check_runner.called_targets and time.monotonic() < deadline_seconds:
            time.sleep(0.01)
    finally:
        poller.stop()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert NAS_TARGET in check_runner.called_targets
