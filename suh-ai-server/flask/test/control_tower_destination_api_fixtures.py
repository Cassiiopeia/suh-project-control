"""관제소 받을 곳 API 테스트 공통: 비밀값·URL 상수, 가짜 Apprise 발송, 테스트 클라이언트, 추가·관리 목록 조회"""
from __future__ import annotations

import pytest

from control_tower_admin_fixtures import REGISTRY, FakePoller, _snapshot, make_app
from service import secret_cipher
from service.control_tower import destination_delivery, runtime as runtime_module
from service.control_tower.runtime import ControlTowerRuntime

SECRET_VALUE = "tower-secret-for-destination-api"
WEBHOOK_TOKEN = "secret-webhook-token-value-zz99"
DISCORD_URL = f"discord://1234567890/{WEBHOOK_TOKEN}"
CREATE_PATH = "/control/projects/elum/destinations"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    # 테스트 속도: 반복 횟수만 낮춤 (알고리즘 동일)
    monkeypatch.setattr(secret_cipher, "PBKDF2_ITERATIONS", 1000)


@pytest.fixture
def fake_apprise_sends(monkeypatch):
    """Apprise 발송 경계 교체: (url, 제목, 본문) 기록 > 성공"""
    sends = []

    def fake_send(url, title, body):
        sends.append((url, title, body))
        return True

    monkeypatch.setattr(destination_delivery, "_send_with_apprise", fake_send)
    return sends


@pytest.fixture
def destination_client(store, dispatcher, monkeypatch):
    monkeypatch.setenv("CONTROL_TOWER_SECRET", SECRET_VALUE)
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=FakePoller(_snapshot()),
        file_registry_provider=lambda: REGISTRY))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


def _create(client, kind="error", label="팀 디스코드", url=DISCORD_URL):
    return client.post(CREATE_PATH, json={"kind": kind, "label": label, "url": url})


def _manage_destinations(client, project_id="elum") -> list[dict]:
    projects = client.get("/control/manage").get_json()["projects"]
    return next(project for project in projects if project["id"] == project_id)["destinations"]
