"""관제소 프로젝트 이벤트 토큰 관리 API: 발급·교체 201, 폐기 204·404, 없는 프로젝트 404, 비밀값 없음 409, 503, 감사, 관리 목록 상태, 원문 노출 없음"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    NOW, REGISTRY, FakePoller, _snapshot, dispatcher, make_app, store,
)
from service.audit_service import AuditAction
from service.control_tower import runtime as runtime_module
from service.control_tower.override_models import CustomProject
from service.control_tower.project_event_tokens import is_project_token_valid
from service.control_tower.runtime import ControlTowerRuntime

TOKEN_PATH = "/control/projects/elum/event-token"
SECRET_VALUE = "tower-secret-for-api-test"


@pytest.fixture
def token_client(store, dispatcher, monkeypatch):
    monkeypatch.setenv("CONTROL_TOWER_SECRET", SECRET_VALUE)
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=FakePoller(_snapshot()),
        file_registry_provider=lambda: REGISTRY))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _manage_project(client, project_id: str) -> dict:
    projects = client.get("/control/manage").get_json()["projects"]
    return next(project for project in projects if project["id"] == project_id)


# ---- POST /control/projects/<id>/event-token ----

def test_발급하면_201과_검증_통과하는_토큰을_돌려준다(token_client, store):
    response = token_client.post(TOKEN_PATH)

    assert response.status_code == 201
    body = response.get_json()
    assert body["previous_expires_at"] is None
    assert is_project_token_valid(store, "elum", body["token"], _now())


def test_연속_2회_발급하면_두번째가_현재_첫번째가_이전(token_client, store):
    first_token = token_client.post(TOKEN_PATH).get_json()["token"]

    second_body = token_client.post(TOKEN_PATH).get_json()

    assert second_body["previous_expires_at"] is not None
    assert is_project_token_valid(store, "elum", second_body["token"], _now())
    assert is_project_token_valid(store, "elum", first_token, _now())
    token_status = _manage_project(token_client, "elum")["event_token"]
    assert token_status["is_db_managed"] is True
    assert token_status["has_current"] is True
    assert token_status["has_previous"] is True
    assert token_status["previous_expires_at"] == second_body["previous_expires_at"]


def test_발급하면_감사_상세에_project_id만_남는다(token_client):
    with patch("util.audit_helper.audit_service.record") as record:
        response = token_client.post(TOKEN_PATH)

    assert record.call_args.args[1] == AuditAction.CONTROL_EVENT_TOKEN_ISSUE
    assert record.call_args.args[3] == {"project_id": "elum"}
    assert response.get_json()["token"] not in repr(record.call_args)


def test_토큰_원문이_관리_목록_감사_로그에_없다(token_client, caplog):
    caplog.set_level(logging.DEBUG)
    with patch("util.audit_helper.audit_service.record") as record:
        first_token = token_client.post(TOKEN_PATH).get_json()["token"]
        second_token = token_client.post(TOKEN_PATH).get_json()["token"]
        token_client.delete(TOKEN_PATH)

    manage_text = token_client.get("/control/manage").get_data(as_text=True)
    audit_text = repr(record.call_args_list)
    for token in (first_token, second_token):
        assert token not in manage_text
        assert token not in audit_text
        assert token not in caplog.text
    assert SECRET_VALUE not in manage_text + audit_text + caplog.text


def test_관리_화면에서_만든_프로젝트에도_발급된다(token_client, store):
    store.insert_custom_project(CustomProject("side", "사이드"), NOW)

    response = token_client.post("/control/projects/side/event-token")

    assert response.status_code == 201
    assert is_project_token_valid(store, "side", response.get_json()["token"], _now())


def test_없는_프로젝트는_404(token_client):
    response = token_client.post("/control/projects/nope/event-token")

    assert response.status_code == 404
    assert response.get_json() == {"error": "unknown_project"}


def test_비밀값이_없으면_409(token_client, store, monkeypatch):
    monkeypatch.delenv("CONTROL_TOWER_SECRET")

    response = token_client.post(TOKEN_PATH)

    assert response.status_code == 409
    assert response.get_json() == {"error": "secret_not_configured"}
    assert store.load_project_token_state("elum").is_db_managed is False


def test_런타임이_없으면_발급_폐기_모두_503():
    runtime_module.set_runtime(None)
    client = make_app().test_client()

    assert client.post(TOKEN_PATH).status_code == 503
    assert client.delete(TOKEN_PATH).status_code == 503


# ---- DELETE /control/projects/<id>/event-token ----

def test_폐기하면_204_이후_다시_폐기하면_404(token_client, store):
    token = token_client.post(TOKEN_PATH).get_json()["token"]

    with patch("util.audit_helper.audit_service.record") as record:
        response = token_client.delete(TOKEN_PATH)

    assert response.status_code == 204
    assert record.call_args.args[1] == AuditAction.CONTROL_EVENT_TOKEN_REVOKE
    assert record.call_args.args[3] == {"project_id": "elum"}
    assert not is_project_token_valid(store, "elum", token, _now())
    second_response = token_client.delete(TOKEN_PATH)
    assert second_response.status_code == 404
    assert second_response.get_json() == {"error": "no_token"}
    # 폐기 후에도 DB 관리 유지
    assert _manage_project(token_client, "elum")["event_token"]["is_db_managed"] is True


def test_발급한_적_없는_프로젝트_폐기는_404(token_client):
    response = token_client.delete(TOKEN_PATH)

    assert response.status_code == 404
    assert response.get_json() == {"error": "no_token"}


def test_없는_프로젝트_폐기는_404(token_client):
    response = token_client.delete("/control/projects/nope/event-token")

    assert response.status_code == 404
    assert response.get_json() == {"error": "unknown_project"}


# ---- GET /control/manage 토큰 상태 ----

def test_관리_목록에_토큰_상태와_비밀값_설정_여부가_있다(token_client, monkeypatch):
    monkeypatch.setenv("CONTROL_EVENT_TOKEN_ELUM", "env-token")

    body = token_client.get("/control/manage").get_json()

    assert body["is_token_secret_configured"] is True
    elum_status = next(project for project in body["projects"] if project["id"] == "elum")["event_token"]
    assert elum_status == {"is_db_managed": False, "has_current": False, "current_created_at": None,
                           "has_previous": False, "previous_count": 0, "previous_expires_at": None,
                           "is_env_configured": True}


def test_비밀값이_없으면_관리_목록에_미설정으로_표시된다(token_client, monkeypatch):
    monkeypatch.delenv("CONTROL_TOWER_SECRET")

    assert token_client.get("/control/manage").get_json()["is_token_secret_configured"] is False
