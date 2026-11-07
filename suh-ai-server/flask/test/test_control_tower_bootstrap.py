"""관제소 기동 조립: env 없으면 디스코드·심박 없이 폴러만, env 있으면 심박·동기화 연결, 런타임 등록"""
from __future__ import annotations

import time

import pytest

from service.control_tower import bootstrap
from service.control_tower import runtime as runtime_module
from service.control_tower.heartbeat_client import HeartbeatClient

REGISTRY_YAML = """
projects:
  - id: elum
    name: 이룸
    services:
      - id: elum-api
        name: 이룸 API
        checks:
          external: {url: "https://api.elum.example.com/"}
"""


@pytest.fixture
def paths(tmp_path):
    registry_path = tmp_path / "services.yml"
    registry_path.write_text(REGISTRY_YAML, encoding="utf-8")
    return str(tmp_path / "data" / "control_tower.db"), str(registry_path)


@pytest.fixture(autouse=True)
def stop_started_poller(monkeypatch):  # monkeypatch 복원보다 먼저 정지
    yield
    started_runtime = runtime_module.get_runtime()
    if started_runtime is not None and started_runtime.poller is not None:
        started_runtime.poller.stop()
    runtime_module.set_runtime(None)


def _wait_until(condition, timeout_seconds: float = 5.0) -> None:
    deadline_seconds = time.monotonic() + timeout_seconds
    while not condition() and time.monotonic() < deadline_seconds:
        time.sleep(0.01)


def test_env가_없으면_디스코드·심박_없이_폴러만_시작하고_런타임을_등록한다(paths, monkeypatch):
    database_path, registry_path = paths
    sync_calls = []
    monkeypatch.setattr(bootstrap, "sync_discord", lambda *arguments: sync_calls.append(arguments))

    started_runtime = bootstrap.start_control_tower({}, database_path, registry_path)

    assert runtime_module.get_runtime() is started_runtime
    assert started_runtime.poller._heartbeat_client is None
    assert started_runtime.dispatcher._discord_client_provider() is None
    _wait_until(lambda: started_runtime.registry_provider().projects != ())
    assert [project.id for project in started_runtime.registry_provider().projects] == ["elum"]
    assert sync_calls == []


def test_env가_있으면_심박_클라이언트와_기동_디스코드_동기화를_연결한다(paths, monkeypatch):
    database_path, registry_path = paths
    sync_calls = []
    monkeypatch.setattr(bootstrap, "sync_discord", lambda *arguments: sync_calls.append(arguments))
    monkeypatch.setattr(HeartbeatClient, "send", lambda self, registry, public_incidents, now: None)
    environ = {"DISCORD_BOT_TOKEN": "bot-token", "DISCORD_GUILD_ID": "9000",
               "CONTROL_TOWER_WORKER_URL": "https://worker.example.com", "CONTROL_TOWER_HMAC_SECRET": "secret"}

    started_runtime = bootstrap.start_control_tower(environ, database_path, registry_path)

    assert isinstance(started_runtime.poller._heartbeat_client, HeartbeatClient)
    assert started_runtime.dispatcher._discord_client_provider() is not None
    _wait_until(lambda: sync_calls != [])
    registry, _, _, guild_id = sync_calls[0]
    assert [project.id for project in registry.projects] == ["elum"] and guild_id == "9000"


def test_기동_동기화는_관리자_버튼과_같은_잠금을_기다린다(paths, monkeypatch):
    from service.control_tower.discord_sync import DISCORD_SYNC_LOCK
    database_path, registry_path = paths
    sync_calls = []
    monkeypatch.setattr(bootstrap, "sync_discord", lambda *arguments: sync_calls.append(arguments))
    monkeypatch.setattr(HeartbeatClient, "send", lambda self, registry, public_incidents, now: None)
    environ = {"DISCORD_BOT_TOKEN": "bot-token", "DISCORD_GUILD_ID": "9000"}

    with DISCORD_SYNC_LOCK:
        bootstrap.start_control_tower(environ, database_path, registry_path)
        time.sleep(0.5)
        assert sync_calls == []
    _wait_until(lambda: sync_calls != [])
    assert len(sync_calls) == 1
