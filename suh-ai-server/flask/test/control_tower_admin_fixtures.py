"""관제소 관리자 API 테스트 공통: 등록 정보, 가짜 폴러·디스코드·발송기, 폴러 스냅샷, 런타임을 심은 Flask 클라이언트"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest
from flask import Flask

from service.control_tower import runtime as runtime_module
from service.control_tower.alert_planner import Notification
from service.control_tower.check_runner import CheckResult
from service.control_tower.poller_snapshot import PollerSnapshot
from service.control_tower.registry import (
    CheckSpec, MaintenanceWindow, ProjectSpec, Registry, ServiceSpec,
)
from service.control_tower.runtime import ControlTowerRuntime
from service.control_tower.state_machine import Observation, ServiceState
from service.control_tower.store import ControlTowerStore

NOW = datetime.now(timezone.utc)
KST_OFFSET = timezone(timedelta(hours=9))

REGISTRY = Registry(
    projects=(ProjectSpec("elum", "이룸"),),
    services=(
        ServiceSpec("elum-api", "이룸 API", "elum", is_public=True, external=CheckSpec("http", "https://api.example.com/")),
        ServiceSpec("elum-batch", "이룸 배치", "elum", status="paused", internal=CheckSpec("http", "http://127.0.0.1:1/")),
        ServiceSpec("elum-old", "이룸 구버전", "elum", status="retired"),
        ServiceSpec("elum-web", "이룸 웹", "elum", internal=CheckSpec("http", "http://127.0.0.1:2/")),
    ),
    infrastructure=(ServiceSpec("nas", "시놀로지 NAS", None, internal=CheckSpec("tcp", "nas.local:5001")),),
    maintenance=(MaintenanceWindow("elum-web", NOW + timedelta(hours=1), "정기 점검"),),
)


class FakePoller:
    def __init__(self, snapshot: PollerSnapshot):
        self._snapshot = snapshot

    def snapshot(self) -> PollerSnapshot:
        return self._snapshot


class FakeDiscordClient:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def send_embed(self, channel_id: str, embed: dict) -> bool:
        self.sent.append((channel_id, embed))
        return True


class FakeDispatcher:
    def __init__(self, is_ok: bool = True):
        self.notifications: list[Notification] = []
        self.is_ok = is_ok

    def dispatch(self, notification: Notification) -> bool:
        self.notifications.append(notification)
        return self.is_ok


def _snapshot() -> PollerSnapshot:
    down_since = NOW - timedelta(minutes=5)
    states = {
        "nas": ServiceState("down", 3, 0, "service_down", down_since, None, True),
        "elum-api": ServiceState("up", 0, 5, None, NOW - timedelta(hours=2), None, False),
    }
    observations = {
        "nas": Observation(CheckResult(False, False, None, 0, "connection_error", NOW), None, False),
        "elum-api": Observation(None, CheckResult(True, True, 200, 6100, None, NOW), True),
    }
    return PollerSnapshot(REGISTRY, MappingProxyType(states), MappingProxyType(observations), NOW)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


@pytest.fixture
def dispatcher():
    return FakeDispatcher()


@pytest.fixture
def discord_client():
    return FakeDiscordClient()


@pytest.fixture
def client(store, dispatcher, discord_client):
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=FakePoller(_snapshot()),
        discord_client_provider=lambda: discord_client, guild_id="9000"))
    yield make_app().test_client()
    runtime_module.set_runtime(None)




def make_app() -> Flask:
    from router.control_tower_router import control_tower_bp
    app = Flask(__name__)
    app.register_blueprint(control_tower_bp)
    return app
