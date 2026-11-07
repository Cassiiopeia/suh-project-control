"""관제소 관리자 동작 API: 디스코드 동기화, 테스트 알림, 점검 창 설정·해제·검증, 런타임 미설정 503"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    KST_OFFSET, NOW, REGISTRY, FakeDispatcher, FakePoller, client, discord_client, dispatcher, make_app, store,
)
from types import MappingProxyType

from service.control_tower import runtime as runtime_module
from service.control_tower.registry import Registry
from service.control_tower.runtime import ControlTowerRuntime


# ---- POST /control/discord/sync ----

def test_sync는_클라이언트가_없으면_503이다(store, dispatcher):
    runtime_module.set_runtime(ControlTowerRuntime(lambda: REGISTRY, store, dispatcher))
    app = make_app()
    try:
        response = app.test_client().post("/control/discord/sync")
    finally:
        runtime_module.set_runtime(None)

    assert response.status_code == 503 and response.get_json() == {"error": "discord_not_configured"}


def test_sync는_길드_id가_없어도_503이다(store, dispatcher, discord_client):
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, discord_client_provider=lambda: discord_client, guild_id=None))
    app = make_app()
    try:
        response = app.test_client().post("/control/discord/sync")
    finally:
        runtime_module.set_runtime(None)

    assert response.status_code == 503


def test_sync는_리포트를_json으로_돌려준다(client, monkeypatch):
    from service.control_tower.discord_sync_models import SyncReport
    calls = []

    def fake_sync(registry, discord_client, store, guild_id):
        calls.append((registry, guild_id))
        return SyncReport(created=2, updated=1, archived=0, errors=["x"], is_onboarding_applied=True)

    monkeypatch.setattr("router.control_tower_admin_api.sync_discord", fake_sync)
    response = client.post("/control/discord/sync")

    assert response.status_code == 200
    assert response.get_json() == {"created": 2, "updated": 1, "archived": 0, "errors": ["x"],
                                   "is_onboarding_applied": True}
    assert calls == [(REGISTRY, "9000")]


def test_sync_중_예외는_500_sync_failed이다(client, monkeypatch):
    def broken_sync(*arguments):
        raise RuntimeError("boom token=secret")

    monkeypatch.setattr("router.control_tower_admin_api.sync_discord", broken_sync)
    response = client.post("/control/discord/sync")

    assert response.status_code == 500 and response.get_json() == {"error": "sync_failed"}
    assert "secret" not in response.get_data(as_text=True)


def test_동기화가_이미_진행_중이면_409이다(client):
    from service.control_tower.discord_sync import DISCORD_SYNC_LOCK
    with DISCORD_SYNC_LOCK:
        response = client.post("/control/discord/sync")

    assert response.status_code == 409 and response.get_json() == {"error": "sync_in_progress"}


def test_등록_정보를_못_읽었으면_동기화를_거절하고_호출하지_않는다(store, dispatcher, discord_client, monkeypatch):
    from service.control_tower.poller_snapshot import PollerSnapshot
    calls = []
    monkeypatch.setattr("router.control_tower_admin_api.sync_discord", lambda *arguments: calls.append(arguments))
    unloaded_snapshot = PollerSnapshot(None, MappingProxyType({}), MappingProxyType({}), None)
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: Registry(projects=(), services=()), store, dispatcher, poller=FakePoller(unloaded_snapshot),
        discord_client_provider=lambda: discord_client, guild_id="9000"))
    try:
        response = make_app().test_client().post("/control/discord/sync")
    finally:
        runtime_module.set_runtime(None)

    assert response.status_code == 409 and response.get_json() == {"error": "registry_unavailable"}
    assert calls == []


def test_프로젝트가_0개인_등록_정보도_동기화를_거절한다(store, dispatcher, discord_client, monkeypatch):
    calls = []
    monkeypatch.setattr("router.control_tower_admin_api.sync_discord", lambda *arguments: calls.append(arguments))
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: Registry(projects=(), services=()), store, dispatcher,
        discord_client_provider=lambda: discord_client, guild_id="9000"))
    try:
        response = make_app().test_client().post("/control/discord/sync")
    finally:
        runtime_module.set_runtime(None)

    assert response.status_code == 409 and response.get_json() == {"error": "registry_unavailable"}
    assert calls == []


# ---- POST /control/test-alert ----

def test_전역_테스트_알림은_alert_종류로_발송한다(client, dispatcher):
    response = client.post("/control/test-alert", json={"scope": "global"})

    assert response.status_code == 200 and response.get_json() == {"sent": True}
    notification = dispatcher.notifications[0]
    assert (notification.scope, notification.kind, notification.severity) == ("global", "alert", "info")
    assert notification.title == "[테스트] 관제소 알림" and notification.body == "관제소 알림 경로 확인용 메시지"
    assert notification.service_ids == () and notification.dedupe_key == ""


def test_프로젝트_테스트_알림은_status_종류로_발송한다(client, dispatcher):
    client.post("/control/test-alert", json={"scope": "elum"})

    assert (dispatcher.notifications[0].scope, dispatcher.notifications[0].kind) == ("elum", "status")


def test_발송_실패는_sent_false이다(client, dispatcher):
    dispatcher.is_ok = False

    assert client.post("/control/test-alert", json={"scope": "global"}).get_json() == {"sent": False}


@pytest.mark.parametrize("payload", [{"scope": "ghost"}, {}, {"scope": 3}, None])
def test_알_수_없는_테스트_알림_대상은_400이다(client, dispatcher, payload):
    response = client.post("/control/test-alert", json=payload)

    assert response.status_code == 400 and response.get_json() == {"error": "invalid", "fields": ["scope"]}
    assert dispatcher.notifications == []


# ---- POST/DELETE /control/maintenance ----

def _future(hours: float = 2) -> str:
    return (datetime.now(KST_OFFSET) + timedelta(hours=hours)).isoformat()


def test_점검_창을_설정하면_저장소에_기록된다(client, store):
    response = client.post("/control/maintenance", json={"service_id": "nas", "until": _future(), "reason": "디스크 교체"})

    assert response.status_code == 200 and response.get_json() == {"ok": True}
    window = store.active_maintenance(datetime.now(timezone.utc))["nas"]
    assert window.reason == "디스크 교체" and window.until.utcoffset() is not None


def test_사유가_없으면_빈_문자열로_저장한다(client, store):
    client.post("/control/maintenance", json={"service_id": "nas", "until": _future()})

    assert store.active_maintenance(datetime.now(timezone.utc))["nas"].reason == ""


def test_Z_접미사_시각도_받는다(client):
    until = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert client.post("/control/maintenance", json={"service_id": "nas", "until": until}).status_code == 200


def test_점검_창을_해제하면_사라진다(client, store):
    store.set_maintenance("nas", NOW + timedelta(hours=1), "x")

    response = client.delete("/control/maintenance/nas")

    assert response.status_code == 200 and response.get_json() == {"ok": True}
    assert "nas" not in store.active_maintenance(datetime.now(timezone.utc))


def test_없는_서비스_점검_설정은_404이다(client, store):
    response = client.post("/control/maintenance", json={"service_id": "ghost", "until": _future()})

    assert response.status_code == 404 and response.get_json() == {"error": "unknown_service"}


def test_retired_서비스_점검_설정은_404이다(client):
    assert client.post("/control/maintenance", json={"service_id": "elum-old", "until": _future()}).status_code == 404


@pytest.mark.parametrize("until", [
    "not-a-date", "2026-11-06T03:00:00", "2020-01-01T00:00:00+09:00", 12345, None, ""])
def test_잘못된_until은_400이다(client, store, until):
    response = client.post("/control/maintenance", json={"service_id": "nas", "until": until})

    assert response.status_code == 400 and response.get_json() == {"error": "invalid", "fields": ["until"]}
    assert store.active_maintenance(datetime.now(timezone.utc)) == {}


@pytest.mark.parametrize("until", ["9999-12-31T23:59:59-12:00", "9999-12-31T23:59:59+14:00", "0001-01-01T00:00:00+14:00"])
def test_범위를_벗어난_until은_500이_아니라_400이다(client, until):
    response = client.post("/control/maintenance", json={"service_id": "nas", "until": until})

    assert response.status_code == 400 and response.get_json() == {"error": "invalid", "fields": ["until"]}


def test_until은_최대_30일_뒤까지만_허용한다(client):
    within_limit = client.post("/control/maintenance", json={"service_id": "nas", "until": _future(24 * 29)})
    beyond_limit = client.post("/control/maintenance", json={"service_id": "nas", "until": _future(24 * 31)})

    assert within_limit.status_code == 200
    assert beyond_limit.status_code == 400 and beyond_limit.get_json()["fields"] == ["until"]


def test_사유가_200자를_넘거나_문자열이_아니면_400이다(client):
    too_long = client.post("/control/maintenance", json={"service_id": "nas", "until": _future(), "reason": "가" * 201})
    wrong_type = client.post("/control/maintenance", json={"service_id": "nas", "until": _future(), "reason": 5})

    assert too_long.status_code == 400 and too_long.get_json()["fields"] == ["reason"]
    assert wrong_type.status_code == 400


def test_service_id가_문자열이_아니면_400이다(client):
    response = client.post("/control/maintenance", json={"service_id": 7, "until": _future()})

    assert response.status_code == 400 and response.get_json() == {"error": "invalid", "fields": ["service_id"]}


def test_사유_200자는_허용한다(client):
    assert client.post("/control/maintenance",
                       json={"service_id": "nas", "until": _future(), "reason": "가" * 200}).status_code == 200


# ---- 런타임 미설정 ----

@pytest.mark.parametrize("method, path", [
    ("get", "/control/overview"), ("post", "/control/discord/sync"), ("post", "/control/test-alert"),
    ("post", "/control/maintenance"), ("delete", "/control/maintenance/nas")])
def test_런타임이_없으면_모든_관리자_API는_503이다(method, path):
    runtime_module.set_runtime(None)
    app = make_app()

    response = getattr(app.test_client(), method)(path)

    assert response.status_code == 503 and response.get_json() == {"error": "unavailable"}
