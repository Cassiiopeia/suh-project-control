"""앱 확인할 일 push 입구(413·400·401·404·403·202, 이전 토큰), overview 요약 키, 일일 요약 섹션"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import pytest

from control_tower_admin_fixtures import REGISTRY, dispatcher, store  # noqa: F401 (pytest 픽스처 재노출)
from control_tower_app_attention_api_fixtures import (  # noqa: F401
    BASE_TIME, attention_client, feedback_item, ingest, ingest_snapshot, save_source, snapshot_document,
)
from service.control_tower.app_attention_fetch import FetchOutcome
from service.control_tower.app_attention_store import new_attention_source_state
from service.control_tower.app_attention_view import build_app_attention_summary
from service.control_tower.digest import build_daily_digest

EVENT_TOKEN_ENV = "CONTROL_EVENT_TOKEN_ELUM"
CURRENT_TOKEN = "current-token"
PUSH_PATH = "/control/attention/elum/api"


@pytest.fixture(autouse=True)
def event_token(monkeypatch):
    monkeypatch.setenv(EVENT_TOKEN_ENV, CURRENT_TOKEN)
    monkeypatch.delenv(EVENT_TOKEN_ENV + "_PREVIOUS", raising=False)


def _push(client, body, token: str = CURRENT_TOKEN, path: str = PUSH_PATH):
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return client.post(path, data=data, content_type="application/json", headers={"X-Control-Token": token})


# ---- push 입구 ----

def test_push는_pull과_같은_처리로_반영하고_버린_항목을_돌려준다(attention_client, store):
    save_source(store, mode="push")
    response = _push(attention_client, snapshot_document(items=[feedback_item(), {"key": "x"}]))

    assert response.status_code == 202
    assert response.get_json() == {"result": "ok", "dropped_items": [{"key": "#1", "reason": "invalid_key"}]}
    assert list(store.load_attention_items("elum", "api")) == ["feedback.new"]
    assert store.get_attention_source_state("elum", "api").is_baseline_done is True


def test_push는_이미_반영한_시각_이하_스냅샷을_stale로_버린다(attention_client, store):
    save_source(store)
    _push(attention_client, snapshot_document(minutes=5))
    response = _push(attention_client, snapshot_document(minutes=1, items=[feedback_item(count=9)]))

    assert response.get_json()["result"] == "stale"
    assert store.load_attention_items("elum", "api")["feedback.new"].count == 3


def test_push_기준선_뒤_새_건은_확인할일_알림으로_나간다(attention_client, store, dispatcher):
    save_source(store)
    _push(attention_client, snapshot_document(minutes=0))
    _push(attention_client, snapshot_document(minutes=1, items=[feedback_item(count=4, total=11)]))

    assert [notification.kind for notification in dispatcher.notifications] == ["attention"]


def test_교체_중인_이전_토큰도_받고_틀린_토큰은_401이다(attention_client, store, monkeypatch):
    save_source(store)
    monkeypatch.setenv(EVENT_TOKEN_ENV + "_PREVIOUS", "previous-token")

    assert _push(attention_client, snapshot_document(), token="previous-token").status_code == 202
    response = _push(attention_client, snapshot_document(minutes=1), token="wrong")
    assert (response.status_code, response.get_json()) == (401, {"error": "unauthorized"})
    assert _push(attention_client, snapshot_document(minutes=2), token="").status_code == 401


def test_토큰_환경변수가_없으면_모든_push를_거부한다(attention_client, store, monkeypatch):
    save_source(store)
    monkeypatch.delenv(EVENT_TOKEN_ENV)

    assert _push(attention_client, snapshot_document()).status_code == 401


def test_본문이_64KB를_넘으면_해석_전에_413이다(attention_client, store):
    save_source(store)
    response = _push(attention_client, b"{" + b" " * 65536 + b"}")

    assert (response.status_code, response.get_json()) == (413, {"error": "too_large"})
    assert store.get_attention_source_state("elum", "api") is None


def test_정확히_64KB인_본문은_받는다(attention_client, store):
    save_source(store)
    body = json.dumps(snapshot_document()).encode("utf-8")
    body = body[:-1] + b" " * (65536 - len(body)) + b"}"

    assert len(body) == 65536 and _push(attention_client, body).status_code == 202


@pytest.mark.parametrize("body", [b"", b"{not json", b"\xff\xfe"])
def test_JSON이_아니면_400이고_상태를_바꾸지_않는다(attention_client, store, body):
    save_source(store)
    response = _push(attention_client, body)

    assert (response.status_code, response.get_json()) == (400, {"error": "invalid"})
    assert store.get_attention_source_state("elum", "api") is None


def test_규격_위반_본문은_202와_invalid_결과로_실패를_기록한다(attention_client, store):
    save_source(store)
    response = _push(attention_client, {"schema": "attention", "version": "2.0"})

    assert response.status_code == 202 and response.get_json()["result"] == "invalid"
    assert store.get_attention_source_state("elum", "api").last_result == "invalid"


def test_없는_소스는_404_pull_전용은_403_꺼진_소스는_403(attention_client, store):
    assert _push(attention_client, snapshot_document()).get_json() == {"error": "unknown_source"}

    save_source(store, mode="pull")
    response = _push(attention_client, snapshot_document())
    assert (response.status_code, response.get_json()) == (403, {"error": "push_disabled"})

    save_source(store, mode="push", is_enabled=False)
    response = _push(attention_client, snapshot_document())
    assert (response.status_code, response.get_json()) == (403, {"error": "source_disabled"})
    assert store.get_attention_source_state("elum", "api") is None


# ---- overview 요약 ----

def test_overview에_앱_확인할_일_요약이_실린다(attention_client, store, ingest):
    source = save_source(store)
    ingest_snapshot(ingest, source, items=[
        feedback_item(level="critical"), feedback_item(key="report.new", level="warning"),
        feedback_item(key="order.wait", count=0), feedback_item(key="ok.item", level="ok"),
        {"key": "disk.usage", "label": "디스크", "kind": "gauge", "value": 95, "limit": 90, "level": "info"},
        {"key": "pay.gateway", "label": "결제", "kind": "state", "state": "ok", "level": "info"},
        {"key": "custom.thing", "label": "기타", "kind": "note", "level": "info"}])

    summary = attention_client.get("/control/overview").get_json()["app_attention_summary"]

    # 열린 항목: critical, warning, gauge 기준 넘김, 모르는 kind (0건·ok·state ok 제외)
    assert summary == {"open_item_count": 4, "warning_count": 1, "critical_count": 1, "failing_source_count": 0}


def test_실패_중이거나_끊김_알림_상태인_켜진_소스만_실패로_센다(store, ingest):
    api = save_source(store, "api")
    batch = save_source(store, "batch")
    save_source(store, "never")
    off = save_source(store, "off", is_enabled=False)
    ingest_snapshot(ingest, api)
    ingest.ingest(batch, FetchOutcome("timeout", None, None, "timeout"), BASE_TIME)
    ingest.ingest(off, FetchOutcome("error", None, None, "http_500"), BASE_TIME)
    assert build_app_attention_summary(store)["failing_source_count"] == 1

    alerted_state = replace(store.get_attention_source_state("elum", "api"), failure_alerted_at=BASE_TIME)
    store.record_attention_failure("elum", "api", alerted_state)
    assert build_app_attention_summary(store)["failing_source_count"] == 2


# ---- 일일 요약 ----

def test_일일_요약에_프로젝트별_열린_항목과_연동_끊긴_소스가_실린다(store, ingest):
    ingest_snapshot(ingest, save_source(store, "api"), items=[feedback_item(), feedback_item(key="report.new")])
    save_source(store, "batch")
    store.record_attention_failure("elum", "batch", replace(new_attention_source_state("elum", "batch"),
                                                            last_attempt_at=BASE_TIME, last_result="timeout",
                                                            consecutive_failures=1))

    body = build_daily_digest(REGISTRY, store, date(2026, 11, 7)).body

    assert body.endswith("앱 확인할 일\n이룸: 열린 항목 2건, 연동 끊김 batch")


def test_열린_항목도_실패_소스도_없으면_일일_요약_섹션을_생략한다(store, ingest):
    ingest_snapshot(ingest, save_source(store), items=[feedback_item(count=0)])

    body = build_daily_digest(REGISTRY, store, date(2026, 11, 7)).body

    assert "앱 확인할 일" not in body
