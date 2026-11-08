"""관제소 폴러 테스트 공통: 등록 파일 YAML, 가짜 시계·점검·발송기·심박, 폴러 생성, 틱 실행"""
from __future__ import annotations

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
    """발송 기록: failing_titles는 예외, undelivered_counts는 제목별 남은 횟수만큼 False, is_configured는 클라이언트 설정 여부"""

    def __init__(self, failing_titles: tuple[str, ...] = (), undelivered_counts: dict[str, int] | None = None,
                 is_configured: bool = True):
        self.notifications = []
        self.failing_titles = failing_titles
        self.undelivered_counts = dict(undelivered_counts or {})
        self.is_configured = is_configured

    def is_delivery_configured(self) -> bool:
        return self.is_configured

    def dispatch(self, notification) -> bool:
        self.notifications.append(notification)
        if notification.title in self.failing_titles:
            raise RuntimeError("discord exploded")
        if not self.is_configured:
            return False
        if self.undelivered_counts.get(notification.title, 0) > 0:
            self.undelivered_counts[notification.title] -= 1
            return False
        return True

    def titles(self) -> list[str]:
        return [notification.title for notification in self.notifications]


class FakeHeartbeatClient:
    """매 호출 response_factory(now) 반환 (None이면 연결 실패, 예외면 raise), 호출·점검 창·썸네일 기록"""

    def __init__(self, response_factory=lambda now: HeartbeatResponse({}, now)):
        self.response_factory = response_factory
        self.calls: list[tuple] = []
        self.maintenance_calls: list[tuple] = []
        self.project_icon_calls: list[dict] = []

    def send(self, registry, public_incidents, now, maintenance=None, project_icons=None):
        self.calls.append((registry, public_incidents, now))
        self.maintenance_calls.append(tuple(maintenance or ()))
        self.project_icon_calls.append(dict(project_icons or {}))
        response = self.response_factory(now)
        if isinstance(response, Exception):
            raise response
        return response


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


def make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client=None):
    return ControlTowerPoller(str(registry_path), store, dispatcher, heartbeat_client,
                              check_runner=check_runner, now=clock, environ={})


def run_ticks(poller: ControlTowerPoller, clock: FakeClock, count: int) -> None:
    for _ in range(count):
        poller.tick()
        clock.advance()
