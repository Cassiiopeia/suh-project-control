"""관제소 서비스 관리 API: 목록·정보, 서비스·프로젝트 덮어쓰기·추가·삭제, 상태 페이지, 검증 400·충돌 409·503"""
from __future__ import annotations

from datetime import timedelta

import pytest

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    NOW, REGISTRY, FakePoller, _snapshot, dispatcher, make_app, store,
)
from service.control_tower import runtime as runtime_module
from service.control_tower.runtime import ControlTowerRuntime


@pytest.fixture
def manage_client(store, dispatcher):
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=FakePoller(_snapshot()), file_registry_provider=lambda: REGISTRY))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


def _services_by_id(body: dict) -> dict:
    return {service["id"]: service for service in body["services"]}


NEW_SERVICE = {"id": "blog", "project_id": "elum", "name": "블로그", "external_url": "https://blog.example.com/"}


# ---- GET /control/manage ----

def test_manage는_retired_인프라_포함_목록과_출처_페이지_설정을_준다(manage_client):
    body = manage_client.get("/control/manage").get_json()
    services = _services_by_id(body)

    assert list(services) == ["elum-api", "elum-batch", "elum-old", "elum-web", "nas"]
    assert services["elum-old"]["status"] == "retired"
    assert services["nas"]["is_infrastructure"] is True and services["nas"]["url"] is None
    assert services["elum-api"]["source"] == "registry" and services["elum-api"]["runtime_status"] == "up"
    assert body["page"]["title"] == "SUHSAECHAN Status" and body["page"]["preview_url"].startswith("https://")
    assert body["projects"][0] == {"id": "elum", "name": "이룸", "is_hidden": False, "sort_order": None,
                                   "source": "registry", "original_name": "이룸", "overridden_fields": [],
                                   "invite_url": None, "icon_data_url": None, "icon_source_url": None,
                                   "event_kinds": []}
    assert body["external_checks"]["used"] == 1
    assert "nas.local" not in str(body)


def test_manage는_덮어쓴_칸과_원본_값을_구분한다(manage_client):
    manage_client.patch("/control/services/elum-api", json={"name": "새 API", "is_public": False})

    service = _services_by_id(manage_client.get("/control/manage").get_json())["elum-api"]

    assert service["name"] == "새 API" and service["original"]["name"] == "이룸 API"
    assert sorted(service["overridden_fields"]) == ["is_public", "name"]
    assert service["is_public"] is False and service["is_listed_publicly"] is False


def test_숨긴_프로젝트_서비스는_공개_설정은_유지하고_실제_공개만_꺼진다(manage_client):
    manage_client.patch("/control/projects/elum", json={"is_hidden": True})

    service = _services_by_id(manage_client.get("/control/manage").get_json())["elum-api"]

    assert service["is_public"] is True and service["is_listed_publicly"] is False


# ---- PATCH /control/services/<id> ----

def test_서비스_덮어쓰기와_null_되돌리기(manage_client, store):
    assert manage_client.patch("/control/services/elum-web", json={"status": "retired", "sort_order": 2}).status_code == 200
    assert manage_client.patch("/control/services/elum-web", json={"status": None}).status_code == 200

    override = store.load_registry_overrides().service_overrides["elum-web"]
    assert override.status is None and override.sort_order == 2


@pytest.mark.parametrize("payload, field_name", [
    ({"status": "deleted"}, "status"), ({"name": ""}, "name"), ({"name": "가" * 61}, "name"),
    ({"is_public": "yes"}, "is_public"), ({"sort_order": -1}, "sort_order"), ({"sort_order": True}, "sort_order"),
    ({"external_url": "ftp://x"}, "external_url"), ({"external_url": "https://" + "a" * 2050}, "external_url"),
    ({"unknown": 1}, "unknown"), ({}, "body"),
])
def test_서비스_덮어쓰기_검증_실패는_400과_칸_이름(manage_client, payload, field_name):
    response = manage_client.patch("/control/services/elum-api", json=payload)

    assert response.status_code == 400 and field_name in response.get_json()["fields"]


def test_인프라의_공개_외부_주소_덮어쓰기는_400이고_이름_상태는_된다(manage_client):
    assert manage_client.patch("/control/services/nas", json={"is_public": True}).status_code == 400
    assert manage_client.patch("/control/services/nas", json={"name": "NAS", "status": "paused"}).status_code == 200


def test_없는_서비스_덮어쓰기는_404(manage_client):
    assert manage_client.patch("/control/services/nope", json={"name": "x"}).status_code == 404


def test_외부_점검_상한을_넘기는_재추적은_409(manage_client, monkeypatch):
    from router import control_tower_manage_api
    monkeypatch.setattr(control_tower_manage_api, "MAX_EXTERNAL_CHECKS", 1)

    response = manage_client.patch("/control/services/elum-web", json={"external_url": "https://web.example.com/"})

    assert response.status_code == 409 and response.get_json()["error"] == "external_check_limit"


# ---- POST·DELETE /control/services ----

def test_서비스_추가는_201이고_기본값은_active_비공개다(manage_client, store):
    response = manage_client.post("/control/services", json=NEW_SERVICE)

    assert response.status_code == 201
    custom = store.load_registry_overrides().custom_services[0]
    assert (custom.id, custom.status, custom.is_public) == ("blog", "active", False)
    assert _services_by_id(manage_client.get("/control/manage").get_json())["blog"]["source"] == "custom"


@pytest.mark.parametrize("override, field_name", [
    ({"id": "Bad_ID"}, "id"), ({"id": "a"}, "id"), ({"name": None}, "name"),
    ({"external_url": "blog.example.com"}, "external_url"), ({"status": "gone"}, "status"),
])
def test_서비스_추가_검증_실패는_400(manage_client, override, field_name):
    response = manage_client.post("/control/services", json={**NEW_SERVICE, **override})

    assert response.status_code == 400 and field_name in response.get_json()["fields"]


def test_서비스_추가_id_충돌은_409_없는_프로젝트는_404(manage_client):
    assert manage_client.post("/control/services", json={**NEW_SERVICE, "id": "elum-api"}).status_code == 409
    assert manage_client.post("/control/services", json={**NEW_SERVICE, "id": "nas"}).status_code == 409
    manage_client.post("/control/services", json=NEW_SERVICE)
    assert manage_client.post("/control/services", json=NEW_SERVICE).status_code == 409
    assert manage_client.post("/control/services", json={**NEW_SERVICE, "id": "x-1", "project_id": "nope"}
                              ).status_code == 404


def test_등록_파일_서비스_삭제는_409_사용자_추가_서비스는_삭제된다(manage_client):
    manage_client.post("/control/services", json=NEW_SERVICE)

    assert manage_client.delete("/control/services/elum-api").status_code == 409
    assert manage_client.delete("/control/services/blog").status_code == 200
    assert manage_client.delete("/control/services/blog").status_code == 404


# ---- GET /control/services/<id> ----

def test_서비스_정보는_내부_점검_대상과_최근_장애_일별_가동률을_담는다(manage_client, store):
    store.open_incident("nas", "service_down", NOW - timedelta(hours=1))

    body = manage_client.get("/control/services/nas").get_json()

    assert body["checks"]["internal"]["target"] == "nas.local:5001"
    assert body["state"]["status"] == "down" and body["last_checks"]["internal"]["is_ok"] is False
    assert len(body["incidents"]) == 1 and body["incidents"][0]["ended_at"] is None
    assert body["uptime_days"] == []
    assert manage_client.get("/control/services/nope").status_code == 404


# ---- 프로젝트 ----

def test_프로젝트_추가_덮어쓰기와_검증(manage_client):
    assert manage_client.post("/control/projects", json={"id": "blog", "name": "블로그"}).status_code == 201
    assert manage_client.post("/control/projects", json={"id": "blog", "name": "또"}).status_code == 409
    assert manage_client.post("/control/projects", json={"id": "elum", "name": "또"}).status_code == 409
    assert manage_client.post("/control/projects", json={"id": "-x", "name": "x"}).status_code == 400
    assert manage_client.patch("/control/projects/blog", json={"sort_order": 0, "name": "내 블로그"}).status_code == 200
    assert manage_client.patch("/control/projects/blog", json={"is_hidden": "y"}).status_code == 400
    assert manage_client.patch("/control/projects/nope", json={"name": "x"}).status_code == 404

    projects = manage_client.get("/control/manage").get_json()["projects"]
    assert [(project["id"], project["name"], project["source"]) for project in projects] == [
        ("blog", "내 블로그", "custom"), ("elum", "이룸", "registry")]


# ---- 상태 페이지 ----

def test_상태_페이지_설정과_검증(manage_client):
    assert manage_client.patch("/control/status-page", json={
        "title": "SUH 상태", "notice_text": "점검 예정", "notice_level": "warning"}).status_code == 200
    assert manage_client.patch("/control/status-page", json={"notice_text": "가" * 301}).status_code == 400
    assert manage_client.patch("/control/status-page", json={"notice_level": "loud"}).status_code == 400
    assert manage_client.patch("/control/status-page", json={"title": ""}).status_code == 400

    page = manage_client.get("/control/manage").get_json()["page"]
    assert (page["title"], page["notice_text"], page["notice_level"]) == ("SUH 상태", "점검 예정", "warning")


def test_변경_API는_감사_기록을_남긴다(manage_client, monkeypatch):
    from util import audit_helper
    recorded = []
    monkeypatch.setattr(audit_helper.audit_service, "record",
                        lambda category, action, *arguments, **keywords: recorded.append((category, action)))

    manage_client.patch("/control/status-page", json={"title": "SUH"})

    assert [(category.value, action.value) for category, action in recorded] == [
        ("CONTROL_TOWER", "CONTROL_STATUS_PAGE_UPDATE")]


@pytest.mark.parametrize("method, path", [
    ("get", "/control/manage"), ("patch", "/control/services/elum-api"), ("post", "/control/services"),
    ("delete", "/control/services/blog"), ("get", "/control/services/nas"), ("patch", "/control/projects/elum"),
    ("post", "/control/projects"), ("patch", "/control/status-page"), ("get", "/control/dns-candidates"),
])
def test_런타임이_없으면_503(method, path):
    runtime_module.set_runtime(None)

    response = getattr(make_app().test_client(), method)(path, json={"name": "x"})

    assert response.status_code == 503
