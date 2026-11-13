"""관제소 받을 곳 관리 API: 추가 201·400·404·409·503, 사용 전환(끄기는 비밀값 없어도), 삭제(비밀값 없어도), 테스트 발송(가짜 Apprise 1건), 감사 4종"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from control_tower_admin_fixtures import NOW, dispatcher, make_app, store  # noqa: F401 (pytest 픽스처 재노출)
from control_tower_destination_api_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    CREATE_PATH, DISCORD_URL, WEBHOOK_TOKEN, _create, destination_client, fake_apprise_sends, fast_kdf,
)
from service.audit_service import AuditAction
from service.control_tower import destination_delivery, runtime as runtime_module
from service.control_tower.destination_validation import DESTINATION_LABEL_MAX_LENGTH, DESTINATION_URL_MAX_LENGTH
from service.control_tower.registry_models import EventKindSpec, PROJECT_CHANNEL_KINDS


# ---- POST /control/projects/<id>/destinations ----

def test_추가하면_201과_힌트만_돌려주고_암호문으로_저장한다(destination_client, store):
    response = _create(destination_client)

    assert response.status_code == 201
    body = response.get_json()
    assert body == {"destination_id": body["destination_id"], "kind": "error", "label": "팀 디스코드",
                    "url_hint": "discord://…zz99", "is_enabled": True}
    stored = store.list_destinations("elum")
    assert [destination.destination_id for destination in stored] == [body["destination_id"]]
    assert WEBHOOK_TOKEN.encode() not in stored[0].url_encrypted


@pytest.mark.parametrize("payload, expected_fields", [
    ({"kind": "unknown-kind", "label": "팀", "url": DISCORD_URL}, ["kind"]),
    ({"kind": "info", "label": "팀", "url": DISCORD_URL}, ["kind"]),
    ({"kind": "error", "label": "  ", "url": DISCORD_URL}, ["label"]),
    ({"kind": "error", "label": "가" * (DESTINATION_LABEL_MAX_LENGTH + 1), "url": DISCORD_URL}, ["label"]),
    ({"kind": "error", "label": "팀", "url": "nope://not-a-service"}, ["url"]),
    ({"kind": "error", "label": "팀", "url": ""}, ["url"]),
    ({"kind": "error", "label": "팀", "url": DISCORD_URL + "a" * DESTINATION_URL_MAX_LENGTH}, ["url"]),
    ({"kind": 1, "label": None}, ["kind", "label", "url"]),
])
def test_잘못된_값은_400_fields(destination_client, store, payload, expected_fields):
    response = destination_client.post(CREATE_PATH, json=payload)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid", "fields": expected_fields}
    assert store.list_destinations() == []


def test_종류는_기본_채널_5종과_그_프로젝트_사용자_정의_종류(destination_client, store):
    store.insert_project_event_kind("elum", EventKindSpec("claude-code", "claude-code", ()), NOW)

    for kind in PROJECT_CHANNEL_KINDS + ("claude-code",):
        assert _create(destination_client, kind=kind).status_code == 201
    manage_project = next(project for project in destination_client.get("/control/manage").get_json()["projects"]
                          if project["id"] == "elum")
    assert manage_project["destination_kinds"] == list(PROJECT_CHANNEL_KINDS) + ["claude-code"]


def test_없는_프로젝트는_404(destination_client):
    response = destination_client.post("/control/projects/nope/destinations",
                                       json={"kind": "error", "label": "팀", "url": DISCORD_URL})

    assert response.status_code == 404
    assert response.get_json() == {"error": "unknown_project"}


def test_비밀값이_없으면_추가_409(destination_client, store, monkeypatch):
    monkeypatch.delenv("CONTROL_TOWER_SECRET")

    response = _create(destination_client)

    assert response.status_code == 409
    assert response.get_json() == {"error": "secret_not_configured"}
    assert store.list_destinations() == []


def test_런타임이_없으면_모두_503():
    runtime_module.set_runtime(None)
    client = make_app().test_client()

    assert client.post(CREATE_PATH, json={}).status_code == 503
    assert client.patch("/control/destinations/1", json={"is_enabled": False}).status_code == 503
    assert client.delete("/control/destinations/1").status_code == 503
    assert client.post("/control/destinations/1/test").status_code == 503


# ---- PATCH /control/destinations/<id> ----

def test_사용_전환하면_200과_저장값_변경(destination_client, store):
    destination_id = _create(destination_client).get_json()["destination_id"]

    response = destination_client.patch(f"/control/destinations/{destination_id}", json={"is_enabled": False})

    assert response.status_code == 200
    assert response.get_json()["is_enabled"] is False
    assert store.list_destinations("elum")[0].is_enabled is False


def test_비밀값이_없어도_끄기는_200(destination_client, store, monkeypatch):
    destination_id = _create(destination_client).get_json()["destination_id"]
    monkeypatch.delenv("CONTROL_TOWER_SECRET")

    response = destination_client.patch(f"/control/destinations/{destination_id}", json={"is_enabled": False})

    assert response.status_code == 200
    assert store.list_destinations("elum")[0].is_enabled is False


def test_사용_전환_값이_불리언이_아니면_400_없는_받을_곳은_404_비밀값_없으면_켜기_409(destination_client, monkeypatch):
    destination_id = _create(destination_client).get_json()["destination_id"]

    invalid_response = destination_client.patch(f"/control/destinations/{destination_id}", json={"is_enabled": "no"})
    missing_response = destination_client.patch("/control/destinations/999", json={"is_enabled": True})
    monkeypatch.delenv("CONTROL_TOWER_SECRET")
    secret_response = destination_client.patch(f"/control/destinations/{destination_id}", json={"is_enabled": True})

    assert (invalid_response.status_code, invalid_response.get_json()) == (400, {"error": "invalid",
                                                                                 "fields": ["is_enabled"]})
    assert (missing_response.status_code, missing_response.get_json()) == (404, {"error": "unknown_destination"})
    assert (secret_response.status_code, secret_response.get_json()) == (409, {"error": "secret_not_configured"})


# ---- DELETE /control/destinations/<id> ----

def test_삭제하면_204_다시_삭제하면_404(destination_client, store):
    destination_id = _create(destination_client).get_json()["destination_id"]

    response = destination_client.delete(f"/control/destinations/{destination_id}")

    assert response.status_code == 204
    assert store.list_destinations() == []
    second_response = destination_client.delete(f"/control/destinations/{destination_id}")
    assert (second_response.status_code, second_response.get_json()) == (404, {"error": "unknown_destination"})


def test_비밀값이_없어도_삭제는_204(destination_client, store, monkeypatch):
    destination_id = _create(destination_client).get_json()["destination_id"]
    monkeypatch.delenv("CONTROL_TOWER_SECRET")

    assert destination_client.delete(f"/control/destinations/{destination_id}").status_code == 204
    assert store.list_destinations() == []


# ---- POST /control/destinations/<id>/test ----

def test_테스트_발송은_가짜_Apprise로_1건_보내고_결과를_기록한다(destination_client, store, fake_apprise_sends):
    destination_id = _create(destination_client).get_json()["destination_id"]

    response = destination_client.post(f"/control/destinations/{destination_id}/test")

    assert response.status_code == 200
    assert response.get_json() == {"is_sent": True, "result": destination_delivery.RESULT_SENT}
    assert [url for url, _title, _body in fake_apprise_sends] == [DISCORD_URL]
    stored = store.list_destinations("elum")[0]
    assert stored.last_result == destination_delivery.RESULT_SENT
    assert stored.last_sent_at is not None


def test_테스트_발송_실패는_is_sent_false(destination_client, monkeypatch):
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: False)
    destination_id = _create(destination_client).get_json()["destination_id"]

    response = destination_client.post(f"/control/destinations/{destination_id}/test")

    assert response.get_json() == {"is_sent": False, "result": destination_delivery.RESULT_FAILED}


def test_테스트_발송이_제한_시간을_넘으면_오류_코드(destination_client, monkeypatch):
    monkeypatch.setattr(destination_delivery, "DESTINATION_TEST_TIMEOUT_SECONDS", 0.05)
    release = threading.Event()
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: release.wait(5))
    destination_id = _create(destination_client).get_json()["destination_id"]

    response = destination_client.post(f"/control/destinations/{destination_id}/test")
    release.set()

    assert response.get_json() == {"is_sent": False, "result": destination_delivery.RESULT_TIMEOUT}


def test_테스트_발송_없는_받을_곳_404_비밀값_없으면_409(destination_client, monkeypatch, fake_apprise_sends):
    destination_id = _create(destination_client).get_json()["destination_id"]

    missing_response = destination_client.post("/control/destinations/999/test")
    monkeypatch.delenv("CONTROL_TOWER_SECRET")
    secret_response = destination_client.post(f"/control/destinations/{destination_id}/test")

    assert (missing_response.status_code, missing_response.get_json()) == (404, {"error": "unknown_destination"})
    assert (secret_response.status_code, secret_response.get_json()) == (409, {"error": "secret_not_configured"})
    assert fake_apprise_sends == []


# ---- 감사 ----

def test_감사_액션_4종과_상세에_URL_없음(destination_client, fake_apprise_sends):
    with patch("util.audit_helper.audit_service.record") as record:
        destination_id = _create(destination_client).get_json()["destination_id"]
        destination_client.patch(f"/control/destinations/{destination_id}", json={"is_enabled": False})
        destination_client.post(f"/control/destinations/{destination_id}/test")
        destination_client.delete(f"/control/destinations/{destination_id}")

    actions = [call.args[1] for call in record.call_args_list]
    assert actions == [AuditAction.CONTROL_DESTINATION_CREATE, AuditAction.CONTROL_DESTINATION_UPDATE,
                       AuditAction.CONTROL_DESTINATION_TEST, AuditAction.CONTROL_DESTINATION_DELETE]
    expected_detail = {"destination_id": destination_id, "project_id": "elum", "kind": "error",
                       "label": "팀 디스코드", "url_hint": "discord://…zz99"}
    assert [call.args[3] for call in record.call_args_list] == [
        expected_detail, {**expected_detail, "is_enabled": False}, expected_detail, expected_detail]
    assert WEBHOOK_TOKEN not in repr(record.call_args_list)
