"""관제소 프로젝트 알림 종류 관리 API: 추가·삭제, 검증 400·없음 404·중복 409·503, 감사, 변경 후 디스코드 동기화, 관리 목록 반영"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    NOW, REGISTRY, FakePoller, _snapshot, discord_client, dispatcher, make_app, store,
)
from router import control_tower_event_kind_api
from service.audit_service import AuditAction
from service.control_tower import runtime as runtime_module
from service.control_tower.override_models import CustomProject
from service.control_tower.registry_models import EventKindSpec
from service.control_tower.runtime import ControlTowerRuntime

NEW_KIND = {"kind": "claude-code", "channel_name": "클로드-코드", "visible_to": ["dev", "member"]}
EVENT_KINDS_PATH = "/control/projects/elum/event-kinds"


class SyncRecorder:
    """sync_discord 대체: 받은 (registry, client, store, guild_id) 기록"""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, registry, client, store, guild_id):
        self.calls.append((registry, client, store, guild_id))


@pytest.fixture
def sync_recorder(monkeypatch):
    """백그라운드 실행을 동기 실행으로 바꾸고 동기화 호출 기록"""
    recorder = SyncRecorder()
    monkeypatch.setattr(control_tower_event_kind_api, "run_in_background", lambda task: task())
    monkeypatch.setattr(control_tower_event_kind_api, "sync_discord", recorder)
    return recorder


def _install_runtime(store, dispatcher, discord_client, poller=None):
    # registry_provider는 폴러 캐시 역할 (종류 없는 REGISTRY 고정)
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=poller or FakePoller(_snapshot()),
        discord_client_provider=lambda: discord_client, guild_id="9000" if discord_client else None,
        file_registry_provider=lambda: REGISTRY))


@pytest.fixture
def kind_client(store, dispatcher, discord_client, sync_recorder):
    _install_runtime(store, dispatcher, discord_client)
    yield make_app().test_client()
    runtime_module.set_runtime(None)


# ---- POST /control/projects/<id>/event-kinds ----

def test_종류를_추가하면_201과_저장소에_반영된다(kind_client, store):
    response = kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    assert response.status_code == 201
    assert response.get_json() == {"kind": "claude-code", "channel_name": "클로드-코드", "visible_to": ["dev", "member"]}
    assert store.list_project_event_kinds() == {
        "elum": (EventKindSpec("claude-code", "클로드-코드", ("dev", "member")),)}


def test_채널_이름_공개_대상을_생략하면_기본값을_채운다(kind_client):
    response = kind_client.post(EVENT_KINDS_PATH, json={"kind": "feedback"})

    assert response.status_code == 201
    assert response.get_json() == {"kind": "feedback", "channel_name": "feedback", "visible_to": ["dev"]}


def test_공개_대상_빈_목록은_관리자만으로_저장된다(kind_client, store):
    response = kind_client.post(EVENT_KINDS_PATH, json={"kind": "secret", "visible_to": []})

    assert response.status_code == 201
    assert store.list_project_event_kinds()["elum"][0].visible_to == ()


def test_추가하면_감사_액션이_기록된다(kind_client):
    with patch("util.audit_helper.audit_service.record") as record:
        kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    assert record.call_args.args[1] == AuditAction.CONTROL_EVENT_KIND_CREATE
    assert record.call_args.kwargs["success"] is True


def test_예약된_종류는_400(kind_client):
    response = kind_client.post(EVENT_KINDS_PATH, json={"kind": "status"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid", "fields": ["kind"]}


def test_본문이_객체가_아니면_400(kind_client):
    response = kind_client.post(EVENT_KINDS_PATH, data="[]", content_type="application/json")

    assert response.status_code == 400
    assert response.get_json()["fields"] == ["kind"]


def test_없는_프로젝트는_404(kind_client):
    response = kind_client.post("/control/projects/nope/event-kinds", json=NEW_KIND)

    assert response.status_code == 404
    assert response.get_json() == {"error": "unknown_project"}


def test_관리_화면에서_만든_프로젝트에도_추가된다(kind_client, store):
    store.insert_custom_project(CustomProject("side", "사이드"), NOW)

    response = kind_client.post("/control/projects/side/event-kinds", json=NEW_KIND)

    assert response.status_code == 201
    assert "side" in store.list_project_event_kinds()


def test_이미_있는_종류는_409(kind_client):
    kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    response = kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    assert response.status_code == 409
    assert response.get_json() == {"error": "duplicate_kind"}


def test_런타임이_없으면_추가_삭제_모두_503():
    runtime_module.set_runtime(None)
    client = make_app().test_client()

    assert client.post(EVENT_KINDS_PATH, json=NEW_KIND).status_code == 503
    assert client.delete(EVENT_KINDS_PATH + "/claude-code").status_code == 503


# ---- DELETE /control/projects/<id>/event-kinds/<kind> ----

def test_종류를_삭제하면_204와_저장소에서_빠진다(kind_client, store):
    kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    with patch("util.audit_helper.audit_service.record") as record:
        response = kind_client.delete(EVENT_KINDS_PATH + "/claude-code")

    assert response.status_code == 204
    assert store.list_project_event_kinds() == {}
    assert record.call_args.args[1] == AuditAction.CONTROL_EVENT_KIND_DELETE


def test_없는_종류_삭제는_404(kind_client):
    with patch("util.audit_helper.audit_service.record") as record:
        response = kind_client.delete(EVENT_KINDS_PATH + "/claude-code")

    assert response.status_code == 404
    assert response.get_json() == {"error": "unknown_kind"}
    assert record.call_args.args[1] == AuditAction.CONTROL_EVENT_KIND_DELETE
    assert record.call_args.kwargs["success"] is False


# ---- 변경 후 디스코드 동기화 ----

def test_추가_성공_후_새_종류가_든_실효_등록_정보로_동기화_1회(kind_client, sync_recorder, discord_client, store):
    kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    assert len(sync_recorder.calls) == 1
    registry, client, synced_store, guild_id = sync_recorder.calls[0]
    elum = next(project for project in registry.projects if project.id == "elum")
    # 폴러 캐시(REGISTRY, 종류 없음)가 아니라 저장소를 다시 병합한 등록 정보
    assert [spec.kind for spec in elum.event_kinds] == ["claude-code"]
    assert (client, synced_store, guild_id) == (discord_client, store, "9000")


def test_삭제_성공_후_종류가_빠진_등록_정보로_동기화(kind_client, sync_recorder):
    kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    kind_client.delete(EVENT_KINDS_PATH + "/claude-code")

    assert len(sync_recorder.calls) == 2
    elum = next(project for project in sync_recorder.calls[1][0].projects if project.id == "elum")
    assert elum.event_kinds == ()


def test_실패_응답에서는_동기화하지_않는다(kind_client, sync_recorder):
    kind_client.post(EVENT_KINDS_PATH, json={"kind": "status"})
    kind_client.post("/control/projects/nope/event-kinds", json=NEW_KIND)
    kind_client.delete(EVENT_KINDS_PATH + "/claude-code")

    assert sync_recorder.calls == []


def test_디스코드_미설정이면_동기화_생략하고_저장은_성공(store, dispatcher, sync_recorder):
    _install_runtime(store, dispatcher, None)
    try:
        response = make_app().test_client().post(EVENT_KINDS_PATH, json=NEW_KIND)
    finally:
        runtime_module.set_runtime(None)

    assert response.status_code == 201
    assert sync_recorder.calls == []


def test_등록_파일을_아직_못_읽었으면_동기화_생략(store, dispatcher, discord_client, sync_recorder):
    # 빈 등록 정보로 동기화하면 기존 프로젝트 카테고리를 전부 보관 처리하므로 생략
    _install_runtime(store, dispatcher, discord_client, poller=FakePoller(replace(_snapshot(), registry=None)))
    try:
        response = make_app().test_client().post(EVENT_KINDS_PATH, json=NEW_KIND)
    finally:
        runtime_module.set_runtime(None)

    assert response.status_code == 201
    assert sync_recorder.calls == []


def test_동기화_예외는_요청을_깨지_않는다(kind_client, monkeypatch):
    def failing_sync(*arguments):
        raise RuntimeError("discord down")

    monkeypatch.setattr(control_tower_event_kind_api, "sync_discord", failing_sync)

    assert kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND).status_code == 201


# ---- GET /control/manage ----

def test_관리_목록의_프로젝트마다_알림_종류가_있다(kind_client):
    kind_client.post(EVENT_KINDS_PATH, json=NEW_KIND)

    projects = kind_client.get("/control/manage").get_json()["projects"]

    assert projects[0]["event_kinds"] == [
        {"kind": "claude-code", "channel_name": "클로드-코드", "visible_to": ["dev", "member"]}]


def test_관리_목록에_공개_대상_선택지와_기본값이_있다(kind_client):
    body = kind_client.get("/control/manage").get_json()

    assert body["event_kind_options"] == {"visible_role_keys": ["dev", "member"], "default_visible_to": ["dev"]}
