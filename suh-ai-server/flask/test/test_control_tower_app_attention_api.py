"""앱 확인할 일 관리 API: 소스 추가·수정·삭제 검증, 삭제 연쇄, 연결 확인 무저장, 항목 덮어쓰기, 현황, 토큰 값 비노출"""
from __future__ import annotations

import pytest

from control_tower_admin_fixtures import dispatcher, store  # noqa: F401 (pytest 픽스처 재노출)
from control_tower_app_attention_api_fixtures import (  # noqa: F401
    attention_client, feedback_item, ingest, ingest_snapshot, save_source, snapshot_document,
)
from router import control_tower_app_attention_api
from service.control_tower import runtime as runtime_module
from service.control_tower.app_attention_fetch import FetchOutcome

NEW_SOURCE = {"project_id": "elum", "source_id": "api", "url": "https://elum.example/control/attention"}
PULL_TOKEN_ENV = "CONTROL_PULL_TOKEN_ELUM__API"
EVENT_TOKEN_ENV = "CONTROL_EVENT_TOKEN_ELUM"
SECRET_TOKEN = "secret-token-value"


# ---- POST /control/app-attention/sources ----

def test_소스를_추가하면_기본값이_채워지고_목록에_토큰_설정_여부만_나온다(attention_client, monkeypatch):
    monkeypatch.setenv(PULL_TOKEN_ENV, SECRET_TOKEN)
    response = attention_client.post("/control/app-attention/sources", json=NEW_SOURCE)

    assert response.status_code == 201
    source = response.get_json()["source"]
    assert (source["mode"], source["is_enabled"], source["interval_seconds"], source["timeout_seconds"],
            source["stale_after_seconds"]) == ("pull", True, 60, 5, 300)
    assert source["pull_token_env_name"] == PULL_TOKEN_ENV and source["is_pull_token_configured"] is True
    assert source["push_token_env_name"] is None and source["is_push_token_configured"] is None
    assert source["is_token_configured"] is True and source["state"] is None

    listed = attention_client.get("/control/app-attention/sources").get_json()["sources"]
    assert [entry["source_id"] for entry in listed] == ["api"]
    assert listed[0]["project_name"] == "이룸"
    assert SECRET_TOKEN not in str(listed)


def test_push_토큰이_없으면_설정_안_됨으로_보인다(attention_client, monkeypatch):
    monkeypatch.setenv(PULL_TOKEN_ENV, SECRET_TOKEN)
    monkeypatch.delenv(EVENT_TOKEN_ENV, raising=False)
    source = attention_client.post("/control/app-attention/sources", json={**NEW_SOURCE, "mode": "both"}).get_json()

    assert source["source"]["is_pull_token_configured"] is True
    assert source["source"]["is_push_token_configured"] is False
    assert source["source"]["is_token_configured"] is False


@pytest.mark.parametrize("payload, field_name", [
    ({"source_id": "Api"}, "source_id"), ({"source_id": "a-b"}, "source_id"), ({"source_id": "a" * 21}, "source_id"),
    ({"project_id": "엘룸"}, "project_id"), ({"url": "ftp://x"}, "url"), ({"url": "http://example.com/a"}, "url"),
    ({"url": "http://8.8.8.8/a"}, "url"), ({"url": "https://" + "a" * 2050}, "url"), ({"url": None}, "url"),
    ({"mode": "pushpull"}, "mode"), ({"is_enabled": "yes"}, "is_enabled"), ({"interval_seconds": 59}, "interval_seconds"),
    ({"interval_seconds": 3601}, "interval_seconds"), ({"timeout_seconds": 0}, "timeout_seconds"),
    ({"timeout_seconds": 11}, "timeout_seconds"), ({"stale_after_seconds": 30}, "stale_after_seconds"),
    ({"unknown": 1}, "unknown"),
])
def test_소스_추가_검증_실패는_칸_이름을_돌려준다(attention_client, payload, field_name):
    response = attention_client.post("/control/app-attention/sources", json={**NEW_SOURCE, **payload})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid", "fields": [field_name]}


@pytest.mark.parametrize("url", [
    "http://192.168.0.10:8080/control/attention", "http://10.1.2.3/a", "http://172.20.0.5/a", "http://127.0.0.1:9/a",
    "http://${ELUM_INTERNAL_HOST}/control/attention", "https://any.host.example/a",
])
def test_https와_내부망_http와_치환_주소는_받는다(attention_client, url):
    assert attention_client.post("/control/app-attention/sources", json={**NEW_SOURCE, "url": url}).status_code == 201


def test_push_전용은_주소가_없어도_되고_끊김_판정_기본값이_최소_전송_주기의_2배다(attention_client):
    response = attention_client.post("/control/app-attention/sources",
                                     json={"project_id": "elum", "source_id": "batch", "mode": "push"})

    source = response.get_json()["source"]
    assert response.status_code == 201
    assert source["url"] is None and source["stale_after_seconds"] == 600
    assert source["pull_token_env_name"] is None and source["push_token_env_name"] == EVENT_TOKEN_ENV


def test_없는_프로젝트는_404_이미_있는_소스는_409(attention_client):
    assert attention_client.post("/control/app-attention/sources",
                                 json={**NEW_SOURCE, "project_id": "nope"}).get_json()["error"] == "unknown_project"
    assert attention_client.post("/control/app-attention/sources", json=NEW_SOURCE).status_code == 201
    response = attention_client.post("/control/app-attention/sources", json=NEW_SOURCE)
    assert (response.status_code, response.get_json()) == (409, {"error": "source_exists"})


def test_관리_화면에서_추가한_프로젝트에도_소스를_등록할_수_있다(attention_client):
    assert attention_client.post("/control/projects", json={"id": "passql", "name": "패스큐엘"}).status_code == 201
    response = attention_client.post("/control/app-attention/sources", json={**NEW_SOURCE, "project_id": "passql"})

    assert response.status_code == 201 and response.get_json()["source"]["project_name"] == "패스큐엘"


# ---- PATCH / DELETE /control/app-attention/sources/<p>/<s> ----

def test_소스_수정은_바꾼_칸만_반영하고_기본_끊김_판정은_주기를_따라간다(attention_client, store):
    attention_client.post("/control/app-attention/sources", json=NEW_SOURCE)
    response = attention_client.patch("/control/app-attention/sources/elum/api",
                                      json={"interval_seconds": 120, "is_enabled": False})

    assert response.status_code == 200
    source = store.get_attention_source("elum", "api")
    assert (source.interval_seconds, source.is_enabled, source.stale_after_seconds) == (120, False, 600)
    assert source.url == NEW_SOURCE["url"]

    attention_client.patch("/control/app-attention/sources/elum/api", json={"stale_after_seconds": 1000})
    attention_client.patch("/control/app-attention/sources/elum/api", json={"interval_seconds": 180})
    assert store.get_attention_source("elum", "api").stale_after_seconds == 1000  # 직접 정한 값은 유지
    attention_client.patch("/control/app-attention/sources/elum/api", json={"stale_after_seconds": None})
    assert store.get_attention_source("elum", "api").stale_after_seconds == 900  # 180 x 5


@pytest.mark.parametrize("payload, field_name", [
    ({}, "body"), ({"source_id": "other"}, "source_id"), ({"mode": "x"}, "mode"), ({"url": "http://example.com/"}, "url"),
    ({"stale_after_seconds": 10}, "stale_after_seconds"),
])
def test_소스_수정_검증_실패는_400이고_저장하지_않는다(attention_client, store, payload, field_name):
    save_source(store)
    response = attention_client.patch("/control/app-attention/sources/elum/api", json=payload)

    assert response.status_code == 400 and response.get_json()["fields"] == [field_name]
    assert store.get_attention_source("elum", "api").mode == "both"


def test_없는_소스의_수정_삭제_항목_연결확인은_404(attention_client):
    base = "/control/app-attention/sources/elum/none"
    assert attention_client.patch(base, json={"is_enabled": False}).get_json() == {"error": "unknown_source"}
    assert attention_client.delete(base).status_code == 404
    assert attention_client.get(base + "/items").status_code == 404
    assert attention_client.post(base + "/test").status_code == 404


def test_소스를_삭제하면_항목_덮어쓰기_상태가_함께_사라진다(attention_client, store, ingest):
    source = save_source(store)
    ingest_snapshot(ingest, source)
    attention_client.patch("/control/app-attention/items/elum/api/feedback.new", json={"label": "의견"})

    assert attention_client.delete("/control/app-attention/sources/elum/api").get_json() == {"ok": True}
    assert store.get_attention_source("elum", "api") is None
    assert store.load_attention_items("elum", "api") == {}
    assert store.load_attention_overrides("elum", "api") == {}
    assert store.get_attention_source_state("elum", "api") is None


# ---- POST .../test ----

def test_연결_확인은_미리보기만_돌려주고_상태_항목을_바꾸지_않는다(attention_client, store, monkeypatch):
    save_source(store)
    fetched_etags = []

    def fake_fetch(source, etag):
        fetched_etags.append(etag)
        return FetchOutcome("ok", snapshot_document(items=[feedback_item(), {"key": "bad key"}]), '"v1"', None)

    monkeypatch.setattr(control_tower_app_attention_api, "fetch_attention", fake_fetch)
    body = attention_client.post("/control/app-attention/sources/elum/api/test").get_json()

    assert fetched_etags == [None]
    assert body["result"] == "ok" and body["error_label"] is None and body["errors"] == []
    assert body["items"] == [{"key": "feedback.new", "label": "새 의견", "kind": "count", "level": "info",
                              "summary": "3건 (전체 10)"}]
    assert body["dropped_items"] == [{"key": "#1", "reason": "invalid_key"}]
    assert store.get_attention_source_state("elum", "api") is None
    assert store.load_attention_items("elum", "api") == {}


def test_연결_확인_실패는_결과와_사유만_돌려준다(attention_client, store, monkeypatch):
    save_source(store)
    monkeypatch.setattr(control_tower_app_attention_api, "fetch_attention",
                        lambda source, etag: FetchOutcome("unauthorized", None, None, "token_missing"))
    body = attention_client.post("/control/app-attention/sources/elum/api/test").get_json()

    assert (body["result"], body["error_label"], body["items"]) == ("unauthorized", "token_missing", [])


# ---- 항목·덮어쓰기 ----

def test_항목_목록은_앱_값_덮어쓰기_유효_값을_함께_준다(attention_client, store, ingest):
    source = save_source(store)
    ingest_snapshot(ingest, source)

    response = attention_client.patch("/control/app-attention/items/elum/api/feedback.new",
                                      json={"label": " 의견 ", "level_policy": "warning", "threshold": 5,
                                            "channel_kind": "status"})
    assert response.get_json() == {"ok": True, "override": {
        "is_hidden": None, "label": "의견", "level_policy": "warning", "alert_rule": None, "threshold": 5.0,
        "channel_kind": "status"}}

    body = attention_client.get("/control/app-attention/sources/elum/api/items").get_json()
    item = body["items"][0]
    assert body["source"]["source_id"] == "api" and body["source"]["item_count"] == 1
    assert item["app"]["label"] == "새 의견" and item["app"]["level"] == "info" and item["app"]["count"] == 3
    assert item["effective"] == {"label": "의견", "level": "warning", "rule": "new", "threshold": 5.0,
                                 "channel_kind": "status", "is_hidden": False, "is_open": True}
    assert item["is_missing"] is False


def test_항목_덮어쓰기는_null로_해제하고_다른_칸은_유지한다(attention_client, store, ingest):
    ingest_snapshot(ingest, save_source(store))
    attention_client.patch("/control/app-attention/items/elum/api/feedback.new",
                           json={"label": "의견", "is_hidden": True})
    attention_client.patch("/control/app-attention/items/elum/api/feedback.new", json={"label": None})

    override = store.load_attention_overrides("elum", "api")["feedback.new"]
    assert override.label is None and override.is_hidden is True


@pytest.mark.parametrize("payload, field_name", [
    ({}, "body"), ({"label": ""}, "label"), ({"label": "가" * 41}, "label"), ({"level_policy": "high"}, "level_policy"),
    ({"alert_rule": "always"}, "alert_rule"), ({"threshold": "5"}, "threshold"), ({"threshold": True}, "threshold"),
    ({"channel_kind": "deploy"}, "channel_kind"), ({"is_hidden": 1}, "is_hidden"), ({"mention_role": "x"}, "mention_role"),
])
def test_항목_덮어쓰기_검증_실패는_400(attention_client, store, ingest, payload, field_name):
    ingest_snapshot(ingest, save_source(store))
    response = attention_client.patch("/control/app-attention/items/elum/api/feedback.new", json=payload)

    assert response.status_code == 400 and response.get_json()["fields"] == [field_name]


def test_모르는_항목과_소스의_덮어쓰기는_404(attention_client, store, ingest):
    ingest_snapshot(ingest, save_source(store))
    assert attention_client.patch("/control/app-attention/items/elum/api/other.key",
                                  json={"label": "x"}).get_json() == {"error": "unknown_item"}
    assert attention_client.patch("/control/app-attention/items/elum/none/feedback.new",
                                  json={"label": "x"}).get_json() == {"error": "unknown_source"}


# ---- GET /control/app-attention ----

def test_현황은_숨긴_항목과_꺼진_소스를_빼고_열린_항목을_먼저_준다(attention_client, store, ingest):
    source = save_source(store)
    ingest_snapshot(ingest, source, items=[
        feedback_item(count=0, total=5), feedback_item(key="report.new", label="신고", level="warning"),
        feedback_item(key="order.wait", label="대기 주문")])
    ingest_snapshot(ingest, save_source(store, "batch", is_enabled=False))
    attention_client.patch("/control/app-attention/items/elum/api/order.wait", json={"is_hidden": True})

    body = attention_client.get("/control/app-attention").get_json()
    project = body["projects"][0]

    assert [entry["id"] for entry in body["projects"]] == ["elum"] and project["name"] == "이룸"
    assert [entry["source_id"] for entry in project["sources"]] == ["api"]
    assert [(item["key"], item["is_open"]) for item in project["items"]] == [
        ("report.new", True), ("feedback.new", False)]
    assert project["open_item_count"] == 1
    assert body["summary"] == {"open_item_count": 1, "warning_count": 1, "critical_count": 0,
                               "failing_source_count": 0}


def test_런타임이_없으면_모든_관리_API가_503(attention_client):
    runtime_module.set_runtime(None)
    responses = [attention_client.get("/control/app-attention"), attention_client.get("/control/app-attention/sources"),
                 attention_client.post("/control/app-attention/sources", json=NEW_SOURCE),
                 attention_client.post("/control/app-attention/sources/elum/api/test")]

    assert {response.status_code for response in responses} == {503}
    assert responses[0].get_json() == {"error": "unavailable"}
