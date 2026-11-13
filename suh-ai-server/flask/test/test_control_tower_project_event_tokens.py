"""관제소 프로젝트 이벤트 토큰: 환경변수 경로 유지, 발급(해시만 저장), DB 관리 전환, 교체 유예, 폐기, 비밀값 없음, 두 입구·소스 목록 연결"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from control_tower_admin_fixtures import REGISTRY, dispatcher, make_app, store  # noqa: F401 (pytest 픽스처 재노출)
from control_tower_app_attention_api_fixtures import (  # noqa: F401
    BASE_TIME, attention_client, ingest, save_source, snapshot_document,
)
from router import control_tower_app_attention_intake
from service.control_tower import project_event_tokens
from service.control_tower import runtime as runtime_module
from service.control_tower.app_attention_view import build_source_entry
from service.control_tower.runtime import ControlTowerRuntime
from service.control_tower.project_event_tokens import (
    TokenSecretNotConfiguredError, describe_project_token, is_project_token_configured, is_project_token_valid,
    is_token_secret_configured, issue_project_token, revoke_project_tokens,
)

NOW = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
ENV_TOKEN = "abc"
SECRET_ENVIRON = {"CONTROL_TOWER_SECRET": "tower-secret", "CONTROL_EVENT_TOKEN_ELUM": ENV_TOKEN}
NO_SECRET_ENVIRON = {"CONTROL_EVENT_TOKEN_ELUM": ENV_TOKEN}


@pytest.fixture(autouse=True)
def reset_secret_missing_warning(monkeypatch):
    # 경고 간격 상태는 프로세스 전역이라 테스트마다 초기화
    monkeypatch.setattr(project_event_tokens, "_last_secret_missing_warning_monotonic", None)


def _all_stored_text(store) -> str:
    """DB 전체 테이블의 모든 행을 문자열로 (원문 저장 여부 검사용)"""
    connection = store._connection()
    table_names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    rows = [tuple(row) for name in table_names for row in connection.execute(f'SELECT * FROM "{name}"')]
    return repr(rows)


def test_env_fallback_when_not_db_managed(store):
    assert is_project_token_valid(store, "elum", ENV_TOKEN, NOW, NO_SECRET_ENVIRON)
    assert not is_project_token_valid(store, "elum", "x", NOW, NO_SECRET_ENVIRON)
    assert is_project_token_configured(store, "elum", NO_SECRET_ENVIRON)
    assert not is_project_token_configured(store, "elum", {})


def test_issue_returns_token_and_stores_only_hash(store):
    token = issue_project_token(store, "elum", NOW, SECRET_ENVIRON)

    assert len(token) >= 43
    assert token not in _all_stored_text(store)
    assert is_project_token_valid(store, "elum", token, NOW, SECRET_ENVIRON)
    assert is_project_token_configured(store, "elum", SECRET_ENVIRON)


def test_db_managed_ignores_env_token(store):
    issue_project_token(store, "elum", NOW, SECRET_ENVIRON)

    assert not is_project_token_valid(store, "elum", ENV_TOKEN, NOW, SECRET_ENVIRON)


def test_rotate_keeps_previous_until_expiry(store):
    token_a = issue_project_token(store, "elum", NOW, SECRET_ENVIRON)
    token_b = issue_project_token(store, "elum", NOW, SECRET_ENVIRON)

    assert token_a != token_b
    assert is_project_token_valid(store, "elum", token_a, NOW, SECRET_ENVIRON)
    assert is_project_token_valid(store, "elum", token_b, NOW, SECRET_ENVIRON)
    after_grace = NOW + timedelta(days=7, seconds=1)
    assert not is_project_token_valid(store, "elum", token_a, after_grace, SECRET_ENVIRON)
    assert is_project_token_valid(store, "elum", token_b, after_grace, SECRET_ENVIRON)

    description = describe_project_token(store, "elum", NOW, SECRET_ENVIRON)
    assert description["has_current"] and description["has_previous"]
    assert description["previous_expires_at"] == (NOW + timedelta(days=7)).isoformat(timespec="microseconds")
    assert describe_project_token(store, "elum", after_grace, SECRET_ENVIRON)["has_previous"] is False


def test_revoke_rejects_everything_and_stays_db_managed(store):
    issue_project_token(store, "elum", NOW, SECRET_ENVIRON)
    token_b = issue_project_token(store, "elum", NOW, SECRET_ENVIRON)

    assert revoke_project_tokens(store, "elum") is True
    assert not is_project_token_valid(store, "elum", token_b, NOW, SECRET_ENVIRON)
    assert not is_project_token_valid(store, "elum", ENV_TOKEN, NOW, SECRET_ENVIRON)
    assert not is_project_token_configured(store, "elum", SECRET_ENVIRON)
    assert describe_project_token(store, "elum", NOW, SECRET_ENVIRON) == {
        "is_db_managed": True, "has_current": False, "current_created_at": None,
        "has_previous": False, "previous_expires_at": None, "is_env_configured": True,
    }
    assert revoke_project_tokens(store, "elum") is False


def test_describe_not_managed_project(store):
    assert describe_project_token(store, "elum", NOW, {"CONTROL_EVENT_TOKEN_ELUM_PREVIOUS": "old"}) == {
        "is_db_managed": False, "has_current": False, "current_created_at": None,
        "has_previous": False, "previous_expires_at": None, "is_env_configured": True,
    }


def test_issue_without_secret_raises(store):
    assert not is_token_secret_configured(NO_SECRET_ENVIRON)
    assert is_token_secret_configured(SECRET_ENVIRON)
    with pytest.raises(TokenSecretNotConfiguredError):
        issue_project_token(store, "elum", NOW, NO_SECRET_ENVIRON)
    assert describe_project_token(store, "elum", NOW, NO_SECRET_ENVIRON)["is_db_managed"] is False


def test_db_managed_without_secret_rejects_with_warning(store, caplog):
    token = issue_project_token(store, "elum", NOW, SECRET_ENVIRON)

    with caplog.at_level(logging.WARNING):
        assert not is_project_token_valid(store, "elum", token, NOW, NO_SECRET_ENVIRON)
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage().startswith("[control-tower event-token]")
    assert token not in caplog.text


def test_secret_missing_warning_is_throttled(store, caplog, monkeypatch):
    token = issue_project_token(store, "elum", NOW, SECRET_ENVIRON)
    clock = {"seconds": 1000.0}
    monkeypatch.setattr(project_event_tokens, "monotonic", lambda: clock["seconds"])

    def count_warnings_after_requests(request_count: int) -> int:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            for _ in range(request_count):
                assert not is_project_token_valid(store, "elum", token, NOW, NO_SECRET_ENVIRON)
        return sum(1 for record in caplog.records if record.levelno == logging.WARNING)

    assert count_warnings_after_requests(5) == 1
    clock["seconds"] += project_event_tokens.SECRET_MISSING_WARNING_INTERVAL_SECONDS - 1
    assert count_warnings_after_requests(3) == 0
    clock["seconds"] += 1
    assert count_warnings_after_requests(3) == 1


def test_revoke_log_distinguishes_nothing_deleted(store, caplog):
    issue_project_token(store, "elum", NOW, SECRET_ENVIRON)
    with caplog.at_level(logging.INFO):
        revoke_project_tokens(store, "elum")
        revoke_project_tokens(store, "elum")
    messages = [record.getMessage() for record in caplog.records if "revoke" in record.getMessage()]
    assert messages == ["[control-tower event-token] revoked : project=elum",
                        "[control-tower event-token] revoke skipped : no tokens project=elum"]


def test_empty_presented_rejected(store):
    token = issue_project_token(store, "elum", NOW, SECRET_ENVIRON)

    assert not is_project_token_valid(store, "elum", "", NOW, SECRET_ENVIRON)
    assert not is_project_token_valid(store, "other", "", NOW, {"CONTROL_EVENT_TOKEN_OTHER": ""})
    assert is_project_token_valid(store, "elum", token, NOW, SECRET_ENVIRON)


def test_other_project_unaffected_by_issue(store):
    issue_project_token(store, "elum", NOW, SECRET_ENVIRON)

    assert is_project_token_valid(store, "other", "other-token", NOW, {"CONTROL_EVENT_TOKEN_OTHER": "other-token"})


# ---- 두 입구·소스 목록 연결 (실제 os.environ 경로) ----

class _AcceptingDispatcher:
    """이벤트 접수만 흉내 (202)"""

    def accept_event(self, project_id, payload, now):
        return 202, {"accepted": True, "deduplicated": False}


@pytest.fixture
def event_client(store):
    runtime_module.set_runtime(ControlTowerRuntime(lambda: REGISTRY, store, _AcceptingDispatcher()))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


@pytest.fixture
def real_environment(monkeypatch):
    for name, value in SECRET_ENVIRON.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CONTROL_EVENT_TOKEN_ELUM_PREVIOUS", raising=False)


def _post_event(client, token: str):
    payload = {"project": "elum", "kind": "report", "severity": "info", "title": "제목"}
    return client.post("/control/events", json=payload, headers={"X-Control-Token": token})


def test_event_intake_uses_db_token_after_issue(real_environment, event_client, store):
    assert _post_event(event_client, ENV_TOKEN).status_code == 202
    token = issue_project_token(store, "elum", datetime.now(timezone.utc))

    assert _post_event(event_client, token).status_code == 202
    assert _post_event(event_client, ENV_TOKEN).status_code == 401


def test_attention_push_uses_db_token_after_issue(real_environment, monkeypatch, attention_client, store):
    monkeypatch.setattr(control_tower_app_attention_intake, "_now", lambda: BASE_TIME + timedelta(minutes=10))
    save_source(store, mode="push")
    token = issue_project_token(store, "elum", BASE_TIME)

    def push(presented: str, minutes: int):
        return attention_client.post("/control/attention/elum/api", json=snapshot_document(minutes=minutes),
                                     headers={"X-Control-Token": presented})

    assert push(ENV_TOKEN, 1).status_code == 401
    assert push(token, 2).status_code == 202


def test_source_entry_push_configured_follows_db_token(real_environment, store):
    source = save_source(store, mode="push")
    assert build_source_entry(store, source, None, "이룸")["is_push_token_configured"] is True

    issue_project_token(store, "elum", NOW)
    assert build_source_entry(store, source, None, "이룸")["is_push_token_configured"] is True
    revoke_project_tokens(store, "elum")
    assert build_source_entry(store, source, None, "이룸")["is_push_token_configured"] is False
