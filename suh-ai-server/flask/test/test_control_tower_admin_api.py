"""관제소 관리자 overview API: 형태, 요약 개수, 점검 창 병합, 메타, 비밀 미노출"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    KST_OFFSET, NOW, REGISTRY, FakeDispatcher, FakePoller, client, discord_client, dispatcher, make_app, store,
)
from service.control_tower import runtime as runtime_module
from service.control_tower.runtime import ControlTowerRuntime


def _services_by_id(body: dict) -> dict:
    return {service["id"]: service for service in body["services"]}


# ---- GET /control/overview ----

def test_overview는_retired를_빼고_인프라_포함_서비스_항목을_돌려준다(client):
    body = client.get("/control/overview").get_json()

    assert sorted(_services_by_id(body)) == ["elum-api", "elum-batch", "elum-web", "nas"]
    assert _services_by_id(body)["nas"]["project_id"] is None
    assert _services_by_id(body)["elum-api"]["project_id"] == "elum"
    assert body["projects"] == [{"id": "elum", "name": "이룸"}]


def test_overview_서비스_항목은_상태_원인_시작_점검_결과를_담는다(client):
    services = _services_by_id(client.get("/control/overview").get_json())

    nas = services["nas"]
    assert nas["status"] == "down" and nas["cause"] == "service_down" and nas["since"] is not None
    assert nas["lifecycle"] == "active" and nas["is_public"] is False
    assert nas["internal"] == {"is_ok": False, "is_slow": False, "status_code": None, "latency_milliseconds": 0,
                               "error": "connection_error", "checked_at": NOW.isoformat()}
    assert nas["external"] is None
    api = services["elum-api"]
    assert api["external"]["is_slow"] is True and api["external"]["status_code"] == 200
    assert api["internal"] is None and api["is_public"] is True


def test_overview에서_관측이_없는_서비스는_상태_unknown_결과_null이다(client):
    batch = _services_by_id(client.get("/control/overview").get_json())["elum-batch"]

    assert batch["status"] == "unknown" and batch["lifecycle"] == "paused"
    assert batch["internal"] is None and batch["external"] is None
    assert batch["cause"] is None and batch["since"] is None


def test_overview_url은_외부_점검_주소만_싣고_내부_주소는_싣지_않는다(client):
    services = _services_by_id(client.get("/control/overview").get_json())

    assert services["elum-api"]["url"] == "https://api.example.com/"
    assert services["nas"]["url"] is None  # 내부 점검(tcp nas.local:5001)만 있는 서비스
    assert "nas.local" not in str(services["nas"])


def test_overview는_등록_파일_점검_창과_관리자_점검_창을_합쳐_보여준다(client, store):
    store.set_maintenance("nas", NOW + timedelta(hours=2), "디스크 교체")
    services = _services_by_id(client.get("/control/overview").get_json())

    assert services["elum-web"]["maintenance"]["reason"] == "정기 점검"
    assert services["elum-web"]["maintenance"]["source"] == "registry"
    assert services["nas"]["maintenance"]["reason"] == "디스크 교체"
    assert services["nas"]["maintenance"]["source"] == "admin"
    assert services["elum-api"]["maintenance"] is None


def test_관리자_점검_창이_등록_파일_창을_덮으면_source는_admin이다(client, store):
    store.set_maintenance("elum-web", NOW + timedelta(hours=3), "연장")

    maintenance = _services_by_id(client.get("/control/overview").get_json())["elum-web"]["maintenance"]

    assert maintenance["source"] == "admin" and maintenance["reason"] == "연장"


def test_overview_요약_개수는_확인필요_점검_장애_정상_순으로_센다(client):
    summary = client.get("/control/overview").get_json()["summary"]

    assert summary == {"ok": 1, "down": 1, "maintenance": 1, "needs_attention": 1}


def test_overview는_장애_이벤트_심박_온보딩_등록오류를_담는다(client, store):
    store.open_incident("nas", "service_down", NOW - timedelta(minutes=5))
    store.record_event("elum", "report", "key-1", NOW)
    store.set_meta("heartbeat_last_ok_at", NOW.isoformat())
    store.set_meta("heartbeat_is_ok", "1")
    store.set_meta("registry_error", "services.yml: bad")
    store.set_meta("discord_onboarding_hash", "abc")

    body = client.get("/control/overview").get_json()

    assert [incident["service_id"] for incident in body["incidents"]] == ["nas"]
    assert body["incidents"][0]["ended_at"] is None
    assert [(event["project_id"], event["kind"]) for event in body["events"]] == [("elum", "report")]
    assert body["heartbeat"] == {"last_ok_at": NOW.isoformat(), "is_ok": True}
    assert body["registry_error"] == "services.yml: bad"
    assert body["onboarding"] == {"is_applied": True}


def test_overview_메타가_없으면_null_false이다(client):
    body = client.get("/control/overview").get_json()

    assert body["registry_error"] is None
    assert body["heartbeat"] == {"last_ok_at": None, "is_ok": None}
    assert body["onboarding"] == {"is_applied": False}
    assert body["incidents"] == [] and body["events"] == []


def test_overview는_토큰과_내부_점검_주소를_싣지_않는다(client):
    text = client.get("/control/overview").get_data(as_text=True)

    # 외부 공개 주소(api.example.com)는 url로 허용, 내부 주소만 금지
    assert "127.0.0.1" not in text and "nas.local" not in text


def test_폴러가_없는_런타임도_overview는_등록_정보만으로_응답한다(store, dispatcher):
    runtime_module.set_runtime(ControlTowerRuntime(lambda: REGISTRY, store, dispatcher))
    app = make_app()
    try:
        body = app.test_client().get("/control/overview").get_json()
    finally:
        runtime_module.set_runtime(None)

    assert all(service["status"] == "unknown" for service in body["services"])
