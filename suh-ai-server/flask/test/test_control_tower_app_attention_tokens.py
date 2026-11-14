"""관제소 토큰: 환경변수 이름 규칙, 현재·이전 토큰 허용, 둘 다 없으면 거부, 이벤트 입구의 _PREVIOUS 수용"""
from __future__ import annotations

import pytest
from flask import Flask

from service.control_tower import runtime as runtime_module
from service.control_tower.app_attention_tokens import (
    event_token_env_name, is_presented_token_valid, is_pull_token_configured, pull_token_env_name,
    read_pull_token, to_env_id)
from service.control_tower.project_token_store import ProjectTokenState
from service.control_tower.runtime import ControlTowerRuntime
from control_tower_discord_fakes import ELUM, make_registry

ENV_NAME = "CONTROL_EVENT_TOKEN_ELUM"
CURRENT_TOKEN = "current-secret"
PREVIOUS_TOKEN = "previous-secret"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in (ENV_NAME, ENV_NAME + "_PREVIOUS", "CONTROL_PULL_TOKEN_ELUM__API"):
        monkeypatch.delenv(name, raising=False)


def test_토큰_환경변수_이름은_대문자와_밑줄로_만들고_pull은_밑줄_2개로_구분한다():
    assert to_env_id("my-app") == "MY_APP"
    assert pull_token_env_name("my-app", "api") == "CONTROL_PULL_TOKEN_MY_APP__API"
    assert event_token_env_name("my-app") == "CONTROL_EVENT_TOKEN_MY_APP"


def test_수집_토큰은_현재_값만_읽고_비어_있으면_없음으로_본다(monkeypatch):
    assert read_pull_token("elum", "api") is None and not is_pull_token_configured("elum", "api")
    monkeypatch.setenv("CONTROL_PULL_TOKEN_ELUM__API_PREVIOUS", PREVIOUS_TOKEN)
    assert read_pull_token("elum", "api") is None
    monkeypatch.setenv("CONTROL_PULL_TOKEN_ELUM__API", "")
    assert not is_pull_token_configured("elum", "api")
    monkeypatch.setenv("CONTROL_PULL_TOKEN_ELUM__API", CURRENT_TOKEN)
    assert read_pull_token("elum", "api") == CURRENT_TOKEN and is_pull_token_configured("elum", "api")


def test_현재_토큰과_이전_토큰을_모두_허용하고_다른_값은_거부한다(monkeypatch):
    monkeypatch.setenv(ENV_NAME, CURRENT_TOKEN)
    monkeypatch.setenv(ENV_NAME + "_PREVIOUS", PREVIOUS_TOKEN)
    assert is_presented_token_valid(ENV_NAME, CURRENT_TOKEN)
    assert is_presented_token_valid(ENV_NAME, PREVIOUS_TOKEN)
    assert not is_presented_token_valid(ENV_NAME, "wrong")
    assert not is_presented_token_valid(ENV_NAME, "")


def test_이전_토큰만_있어도_그_값은_허용한다(monkeypatch):
    monkeypatch.setenv(ENV_NAME + "_PREVIOUS", PREVIOUS_TOKEN)
    assert is_presented_token_valid(ENV_NAME, PREVIOUS_TOKEN)
    assert not is_presented_token_valid(ENV_NAME, CURRENT_TOKEN)


def test_현재_이전_토큰이_모두_없거나_비어_있으면_거부한다(monkeypatch):
    assert not is_presented_token_valid(ENV_NAME, "")
    assert not is_presented_token_valid(ENV_NAME, "anything")
    monkeypatch.setenv(ENV_NAME, "")
    monkeypatch.setenv(ENV_NAME + "_PREVIOUS", "")
    assert not is_presented_token_valid(ENV_NAME, "")


class _AcceptingDispatcher:
    """이벤트 접수만 흉내 (202)"""

    def accept_event(self, project_id, payload, now):
        return 202, {"accepted": True, "deduplicated": False}


class _EnvTokenOnlyStore:
    """DB 발급 토큰 없는 저장소 (환경변수 토큰 경로만 검사)"""

    def load_project_token_state(self, project_id):
        return ProjectTokenState.not_managed()


@pytest.fixture
def event_client():
    from router.control_tower_router import control_tower_bp
    registry = make_registry(ELUM)
    runtime_module.set_runtime(ControlTowerRuntime(lambda: registry, _EnvTokenOnlyStore(), _AcceptingDispatcher()))
    app = Flask(__name__)
    app.register_blueprint(control_tower_bp)
    yield app.test_client()
    runtime_module.set_runtime(None)


def _post_event(client, token: str):
    payload = {"project": "elum", "kind": "report", "severity": "info", "title": "제목"}
    return client.post("/control/events", json=payload, headers={"X-Control-Token": token})


def test_이벤트_입구는_교체_중인_이전_토큰도_받고_틀린_토큰은_401이다(monkeypatch, event_client):
    monkeypatch.setenv(ENV_NAME, CURRENT_TOKEN)
    monkeypatch.setenv(ENV_NAME + "_PREVIOUS", PREVIOUS_TOKEN)
    assert _post_event(event_client, CURRENT_TOKEN).status_code == 202
    assert _post_event(event_client, PREVIOUS_TOKEN).status_code == 202
    response = _post_event(event_client, "wrong")
    assert response.status_code == 401
    assert CURRENT_TOKEN not in response.get_data(as_text=True)
