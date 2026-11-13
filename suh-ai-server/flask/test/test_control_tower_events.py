"""관제소 이벤트 입구·라우팅: 응답 6종, 토큰 인증, 채널 바인딩 대체, 런타임 미설정"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from flask import Flask

from service.control_tower import runtime as runtime_module
from service.control_tower.alert_planner import Notification
from service.control_tower.event_dispatcher import EventDispatcher
from service.control_tower.project_token_store import ProjectTokenState
from service.control_tower.runtime import ControlTowerRuntime
from control_tower_discord_fakes import ELUM, SAMPLE, make_registry

TOKEN_ENV_NAME = "CONTROL_EVENT_TOKEN_ELUM"
TOKEN = "elum-secret-token"
STATUS_PAGE_URL = "https://status.example.com"
NOW = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)

VALID_PAYLOAD = {
    "project": "elum", "kind": "report", "severity": "warning", "title": "신고 접수",
    "body": "신고 123번", "dedupe_key": "report-123", "url": "https://elum.example.com/reports/123",
}


class FakeStore:
    """바인딩 dict + 이벤트 기록(중복 키 억제)"""

    def __init__(self, bindings: dict[tuple[str, str], str] | None = None):
        self.bindings = bindings or {}
        self.recorded: list[tuple] = []
        self.event_kind_names: dict[str, set[str]] = {}  # 프로젝트 id > 사용자 정의 종류 이름

    def list_event_kind_names_of_project(self, project_id: str) -> frozenset[str]:
        return frozenset(self.event_kind_names.get(project_id, ()))

    def get_binding(self, scope: str, kind: str) -> str | None:
        return self.bindings.get((scope, kind))

    def load_project_token_state(self, project_id: str) -> ProjectTokenState:
        # DB 발급 토큰 없음 = 환경변수 토큰 경로
        return ProjectTokenState(False, None, None, ())

    def record_event(self, project_id: str, kind: str, dedupe_key: str | None, created_at: datetime) -> bool:
        if dedupe_key and any(entry[0] == project_id and entry[2] == dedupe_key for entry in self.recorded):
            return False
        self.recorded.append((project_id, kind, dedupe_key, created_at))
        return True


class FakeDiscordClient:
    def __init__(self, is_send_ok: bool = True):
        self.sent: list[tuple[str, dict]] = []
        self.is_send_ok = is_send_ok

    def send_embed(self, channel_id: str, embed: dict) -> bool:
        self.sent.append((channel_id, embed))
        return self.is_send_ok


DEFAULT_BINDINGS = {("elum", "report"): "c-report", ("elum", "status"): "c-status", ("global", "alert"): "c-alert"}


def _make_dispatcher(store: FakeStore, client: FakeDiscordClient | None) -> EventDispatcher:
    return EventDispatcher(store, lambda: client, STATUS_PAGE_URL)


def _notification(scope="elum", kind="report", **overrides) -> Notification:
    fields = dict(scope=scope, kind=kind, severity="warning", title="제목", body="본문", service_ids=(), dedupe_key="")
    fields.update(overrides)
    return Notification(**fields)


@pytest.fixture
def store():
    return FakeStore(dict(DEFAULT_BINDINGS))


@pytest.fixture
def discord_client():
    return FakeDiscordClient()


@pytest.fixture
def dispatcher(store, discord_client):
    return _make_dispatcher(store, discord_client)


@pytest.fixture
def client(monkeypatch, store, dispatcher):
    from router.control_tower_router import control_tower_bp
    monkeypatch.setenv(TOKEN_ENV_NAME, TOKEN)
    registry = make_registry(ELUM, SAMPLE)
    runtime_module.set_runtime(ControlTowerRuntime(lambda: registry, store, dispatcher))
    app = Flask(__name__)
    app.register_blueprint(control_tower_bp)
    yield app.test_client()
    runtime_module.set_runtime(None)


def _post(client, payload=None, token=TOKEN):
    headers = {"X-Control-Token": token} if token is not None else {}
    return client.post("/control/events", json=VALID_PAYLOAD if payload is None else payload, headers=headers)


# ---- 라우터 응답 ----

def test_accepted_event_is_sent_to_kind_channel(client, discord_client):
    response = _post(client)
    assert response.status_code == 202
    assert response.get_json() == {"accepted": True, "deduplicated": False}
    channel_id, embed = discord_client.sent[0]
    assert channel_id == "c-report"
    assert embed["title"] == "신고 접수" and embed["url"] == VALID_PAYLOAD["url"]


def test_duplicate_event_is_accepted_without_sending(client, discord_client):
    _post(client)
    response = _post(client)
    assert response.status_code == 202
    assert response.get_json() == {"accepted": True, "deduplicated": True}
    assert len(discord_client.sent) == 1


def test_wrong_token_returns_401(client, discord_client):
    response = _post(client, token="wrong")
    assert response.status_code == 401 and response.get_json() == {"error": "unauthorized"}
    assert discord_client.sent == []


def test_missing_token_header_returns_401(client):
    assert _post(client, token=None).status_code == 401


def test_project_without_token_env_returns_401(client):
    response = _post(client, {**VALID_PAYLOAD, "project": "sample"}, token=TOKEN)
    assert response.status_code == 401 and response.get_json() == {"error": "unauthorized"}


def test_unknown_project_returns_404(client, monkeypatch):
    monkeypatch.setenv("CONTROL_EVENT_TOKEN_GHOST", TOKEN)
    response = _post(client, {**VALID_PAYLOAD, "project": "ghost"})
    assert response.status_code == 404 and response.get_json() == {"error": "unknown_project"}


def test_hyphenated_project_id_uses_underscore_env_name(monkeypatch, store, discord_client):
    from router.control_tower_router import control_tower_bp
    from control_tower_discord_fakes import make_project
    registry = make_registry(make_project("my-app", "마이앱"))
    monkeypatch.setenv("CONTROL_EVENT_TOKEN_MY_APP", TOKEN)
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: registry, store, EventDispatcher(store, lambda: discord_client, STATUS_PAGE_URL)))
    try:
        app = Flask(__name__)
        app.register_blueprint(control_tower_bp)
        response = _post(app.test_client(), {**VALID_PAYLOAD, "project": "my-app"})
    finally:
        runtime_module.set_runtime(None)
    assert response.status_code == 202


@pytest.mark.parametrize("payload", [None, [], "text", {}, {"project": 1}])
def test_body_without_string_project_returns_400(client, payload):
    response = client.post("/control/events", data=None if payload is None else __import__("json").dumps(payload),
                           content_type="application/json", headers={"X-Control-Token": TOKEN})
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid", "fields": ["project"]}


@pytest.mark.parametrize("overrides,expected_fields", [
    ({"kind": 5}, ["kind"]),  # 문자열이 아닌 kind (문자열 미등록은 unknown_kind)
    ({"severity": "recovered"}, ["severity"]),
    ({"title": ""}, ["title"]),
    ({"title": "가" * 201}, ["title"]),
    ({"body": "나" * 2001}, ["body"]),
    ({"url": "http://insecure.example.com"}, ["url"]),
    ({"url": "https://e.example.com/" + "a" * 2027}, ["url"]),  # 2049자
    ({"dedupe_key": 5}, ["dedupe_key"]),
    ({"kind": 5, "severity": "y", "title": ""}, ["kind", "severity", "title"]),
])
def test_invalid_fields_are_all_reported(client, overrides, expected_fields):
    response = _post(client, {**VALID_PAYLOAD, **overrides})
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid", "fields": expected_fields}


def test_boundary_lengths_are_valid(client):
    response = _post(client, {**VALID_PAYLOAD, "title": "가" * 200, "body": "", "dedupe_key": "k1",
                              "url": "https://e.example.com/" + "a" * 2026})  # url 2048자
    assert response.status_code == 202


def test_validation_failure_is_not_recorded(client, store):
    _post(client, {**VALID_PAYLOAD, "title": ""})
    assert store.recorded == []


def test_dispatch_failure_still_returns_accepted(client, discord_client, caplog):
    discord_client.is_send_ok = False
    with caplog.at_level(logging.WARNING):
        response = _post(client)
    assert response.status_code == 202 and response.get_json() == {"accepted": True, "deduplicated": False}
    assert "[control-tower dispatch]" in caplog.text and TOKEN not in caplog.text


def test_runtime_not_set_returns_503():
    from router.control_tower_router import control_tower_bp
    runtime_module.set_runtime(None)
    app = Flask(__name__)
    app.register_blueprint(control_tower_bp)
    response = app.test_client().post("/control/events", json=VALID_PAYLOAD, headers={"X-Control-Token": TOKEN})
    assert response.status_code == 503 and response.get_json() == {"error": "unavailable"}


# ---- 디스패처 라우팅 ----

def test_info_event_routes_to_status_channel(dispatcher, store, discord_client):
    assert dispatcher.accept_event("elum", {**VALID_PAYLOAD, "kind": "info"}, NOW) == (
        202, {"accepted": True, "deduplicated": False})
    assert discord_client.sent[0][0] == "c-status"


def test_event_without_optional_fields_maps_to_notification(dispatcher, discord_client):
    payload = {"project": "elum", "kind": "report", "severity": "info", "title": "제목"}
    assert dispatcher.accept_event("elum", payload, NOW)[0] == 202
    _, embed = discord_client.sent[0]
    assert embed["description"] == "" and embed["url"] == STATUS_PAGE_URL


def test_missing_binding_falls_back_to_global_alert_with_warning(store, discord_client, caplog):
    del store.bindings[("elum", "report")]
    with caplog.at_level(logging.WARNING):
        assert _make_dispatcher(store, discord_client).dispatch(_notification()) is True
    assert discord_client.sent[0][0] == "c-alert"
    assert "[control-tower dispatch]" in caplog.text


def test_no_binding_and_no_global_alert_returns_false(discord_client):
    assert _make_dispatcher(FakeStore({}), discord_client).dispatch(_notification()) is False
    assert discord_client.sent == []


def test_missing_discord_client_returns_false_with_warning(store, caplog):
    with caplog.at_level(logging.WARNING):
        assert _make_dispatcher(store, None).dispatch(_notification()) is False
    assert "[control-tower dispatch]" in caplog.text


def test_planner_notification_uses_scope_and_kind_binding(dispatcher, discord_client):
    assert dispatcher.dispatch(_notification(scope="global", kind="alert")) is True
    assert dispatcher.dispatch(_notification(scope="elum", kind="info")) is True
    assert [channel_id for channel_id, _ in discord_client.sent] == ["c-alert", "c-status"]


def test_dispatch_does_not_dedupe_planner_notifications(dispatcher, discord_client):
    notification = _notification(dedupe_key="elum-api:down:2026-11-06T00:00:00+00:00")
    dispatcher.dispatch(notification)
    dispatcher.dispatch(notification)
    assert len(discord_client.sent) == 2


def test_dispatch_returns_false_when_send_fails(store):
    assert _make_dispatcher(store, FakeDiscordClient(is_send_ok=False)).dispatch(_notification()) is False


def test_link_url_overrides_status_page_url_in_embed():
    from service.control_tower.discord_messages import to_embed
    embed = to_embed(_notification(link_url="https://elum.example.com/x"), STATUS_PAGE_URL)
    assert embed["url"] == "https://elum.example.com/x"


# ---- 사용자 정의 종류·fields ----

def _custom_kind_client(monkeypatch, store, discord_client):
    """저장소에만 elum claude-code 종류 등록 (등록 정보 캐시는 종류 없음 = 폴러 갱신 전) > 라우터 구성"""
    from router.control_tower_router import control_tower_bp
    store.event_kind_names["elum"] = {"claude-code"}
    registry = make_registry(ELUM, SAMPLE)
    monkeypatch.setenv(TOKEN_ENV_NAME, TOKEN)
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: registry, store, _make_dispatcher(store, discord_client)))
    app = Flask(__name__)
    app.register_blueprint(control_tower_bp)
    return app.test_client()


def test_event_with_custom_kind_is_delivered_to_its_channel(monkeypatch, store, discord_client):
    store.bindings[("elum", "claude-code")] = "c-1"
    try:
        response = _post(_custom_kind_client(monkeypatch, store, discord_client),
                         {**VALID_PAYLOAD, "kind": "claude-code"})
    finally:
        runtime_module.set_runtime(None)
    assert response.status_code == 202
    assert discord_client.sent[0][0] == "c-1"


def test_event_with_unregistered_kind_returns_unknown_kind(client, store, discord_client, caplog):
    with caplog.at_level(logging.WARNING):
        response = _post(client, {**VALID_PAYLOAD, "kind": "feedback"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "unknown_kind", "kind": "feedback"}
    assert caplog.text.count("[control-tower event] unknown kind") == 1
    assert store.recorded == [] and discord_client.sent == []


@pytest.mark.parametrize("fields", [
    [["n", "v"]] * 11,
    [{"name": "가" * 41, "value": "v"}],
    [{"name": "n", "value": "값" * 201}],
    "not-a-list",
    [{"name": "n"}],
    [{"name": "   ", "value": "v"}],
    [{"name": "n", "value": " \t "}],
])
def test_event_fields_validation(client, fields):
    response = _post(client, {**VALID_PAYLOAD, "fields": fields})
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid", "fields": ["fields"]}


def test_event_fields_reach_embed(client, discord_client):
    fields = [{"name": "환경", "value": "prod"}, {"name": "건수", "value": "3"}]
    assert _post(client, {**VALID_PAYLOAD, "fields": fields}).status_code == 202
    assert discord_client.sent[0][1]["fields"] == [
        {"name": "환경", "value": "prod", "inline": True}, {"name": "건수", "value": "3", "inline": True}]
