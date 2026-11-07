"""관제소 디스코드 클라이언트: 요청 형태, 429·5xx 1회 재시도, 4xx 무재시도, 발송 실패 비전파, 채널 관리 DiscordError"""
from __future__ import annotations

import logging

import pytest
import requests

from service.control_tower.discord_client import (
    AUDIT_LOG_REASON, BASE_URL, DiscordClient, DiscordError, MAX_RETRY_AFTER_SECONDS, SERVER_ERROR_RETRY_DELAY_SECONDS,
)

BOT_TOKEN = "secret-bot-token"
GUILD_ID = "111"


class FakeResponse:
    def __init__(self, status_code: int = 200, json_body=None, headers=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {}
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


class FakeSession:
    """응답(또는 예외) 큐를 순서대로 소비하고 호출을 기록"""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _client(*outcomes):
    session = FakeSession(*outcomes)
    sleeps: list[float] = []
    return DiscordClient(BOT_TOKEN, GUILD_ID, session=session, sleep=sleeps.append), session, sleeps


def test_send_embed_posts_embed_without_mentions():
    client, session, sleeps = _client(FakeResponse(200, {}))
    assert client.send_embed("999", {"title": "t"}) is True
    call = session.calls[0]
    assert (call["method"], call["url"]) == ("POST", f"{BASE_URL}/channels/999/messages")
    assert call["json"] == {"embeds": [{"title": "t"}], "allowed_mentions": {"parse": []}}
    assert call["headers"]["Authorization"] == f"Bot {BOT_TOKEN}"
    assert call["timeout"] > 0 and sleeps == []


def test_send_embed_429_sleeps_retry_after_then_retries_once():
    client, session, sleeps = _client(FakeResponse(429, {"retry_after": 1.5}), FakeResponse(200, {}))
    assert client.send_embed("999", {}) is True
    assert sleeps == [1.5] and len(session.calls) == 2


def test_send_embed_429_retry_after_falls_back_to_header_and_is_capped():
    client, _, sleeps = _client(FakeResponse(429, None, headers={"Retry-After": "2"}), FakeResponse(200, {}))
    client.send_embed("999", {})
    assert sleeps == [2.0]
    client, _, sleeps = _client(FakeResponse(429, {"retry_after": 999}), FakeResponse(200, {}))
    client.send_embed("999", {})
    assert sleeps == [MAX_RETRY_AFTER_SECONDS]


def test_send_embed_returns_false_when_second_attempt_also_fails():
    client, session, _ = _client(FakeResponse(429, {"retry_after": 1}), FakeResponse(429, {"retry_after": 1}))
    assert client.send_embed("999", {}) is False
    assert len(session.calls) == 2


def test_send_embed_retries_server_error_once():
    client, session, sleeps = _client(FakeResponse(502), FakeResponse(200, {}))
    assert client.send_embed("999", {}) is True
    assert sleeps == [SERVER_ERROR_RETRY_DELAY_SECONDS] and len(session.calls) == 2


def test_send_embed_retries_network_exception_once_and_never_raises():
    client, session, _ = _client(requests.ConnectionError("boom"), requests.Timeout("slow"))
    assert client.send_embed("999", {}) is False
    assert len(session.calls) == 2


def test_send_embed_401_no_retry_and_log_has_no_token(caplog):
    client, session, sleeps = _client(FakeResponse(401, {"message": "401: Unauthorized"}))
    with caplog.at_level(logging.WARNING):
        assert client.send_embed("999", {}) is False
    assert len(session.calls) == 1 and sleeps == []
    assert "status 401" in caplog.text and BOT_TOKEN not in caplog.text and "Unauthorized" not in caplog.text


def test_management_call_raises_discord_error_on_401_without_retry():
    client, session, _ = _client(FakeResponse(401, {"message": "401: Unauthorized"}))
    with pytest.raises(DiscordError) as error_info:
        client.list_channels()
    assert error_info.value.status_code == 401 and BOT_TOKEN not in str(error_info.value)
    assert len(session.calls) == 1


def test_discord_error_message_truncated_to_200_chars():
    client, _, _ = _client(FakeResponse(400, {"message": "x" * 500}))
    with pytest.raises(DiscordError) as error_info:
        client.list_roles()
    assert len(error_info.value.reason) == 200


def test_management_call_retries_then_raises_on_server_error():
    client, session, _ = _client(FakeResponse(500), FakeResponse(503))
    with pytest.raises(DiscordError) as error_info:
        client.list_channels()
    assert error_info.value.status_code == 503 and len(session.calls) == 2


def test_management_call_network_failure_raises_discord_error():
    client, _, _ = _client(requests.ConnectionError("a"), requests.ConnectionError("b"))
    with pytest.raises(DiscordError) as error_info:
        client.list_channels()
    assert error_info.value.status_code == 0


def test_list_channels_and_roles_get_guild_collections():
    client, session, _ = _client(FakeResponse(200, [{"id": "1"}]), FakeResponse(200, [{"id": "2"}]))
    assert client.list_channels() == [{"id": "1"}]
    assert client.list_roles() == [{"id": "2"}]
    assert [(c["method"], c["url"]) for c in session.calls] == [
        ("GET", f"{BASE_URL}/guilds/{GUILD_ID}/channels"), ("GET", f"{BASE_URL}/guilds/{GUILD_ID}/roles")]
    assert "X-Audit-Log-Reason" not in session.calls[0]["headers"]


def test_create_channel_payload_and_audit_header():
    client, session, _ = _client(FakeResponse(201, {"id": "5"}))
    overwrites = [{"id": "1", "type": 0, "deny": "1024"}]
    assert client.create_channel("상태", 0, "77", overwrites) == {"id": "5"}
    call = session.calls[0]
    assert (call["method"], call["url"]) == ("POST", f"{BASE_URL}/guilds/{GUILD_ID}/channels")
    assert call["json"] == {"name": "상태", "type": 0, "parent_id": "77", "permission_overwrites": overwrites}
    assert call["headers"]["X-Audit-Log-Reason"] == AUDIT_LOG_REASON


def test_create_channel_without_parent_omits_parent_id():
    client, session, _ = _client(FakeResponse(201, {"id": "5"}))
    client.create_channel("이룸", 4, None, [])
    assert "parent_id" not in session.calls[0]["json"]


def test_edit_channel_patches_given_fields():
    client, session, _ = _client(FakeResponse(200, {"id": "5"}))
    client.edit_channel("5", name="새이름", parent_id="9")
    call = session.calls[0]
    assert (call["method"], call["url"]) == ("PATCH", f"{BASE_URL}/channels/5")
    assert call["json"] == {"name": "새이름", "parent_id": "9"}
    assert call["headers"]["X-Audit-Log-Reason"] == AUDIT_LOG_REASON


def test_create_role_is_not_mentionable_nor_hoisted():
    client, session, _ = _client(FakeResponse(200, {"id": "8"}))
    client.create_role("이룸")
    call = session.calls[0]
    assert (call["method"], call["url"]) == ("POST", f"{BASE_URL}/guilds/{GUILD_ID}/roles")
    assert call["json"] == {"name": "이룸", "mentionable": False, "hoist": False}
    assert call["headers"]["X-Audit-Log-Reason"] == AUDIT_LOG_REASON


def test_put_onboarding_true_on_success_false_on_failure_never_raises():
    client, session, _ = _client(FakeResponse(200, {}), FakeResponse(403, {"message": "Missing Access"}),
                                 FakeResponse(400, {"message": "Community required"}))
    assert client.put_onboarding({"enabled": True}) is True
    assert (session.calls[0]["method"], session.calls[0]["url"]) == ("PUT", f"{BASE_URL}/guilds/{GUILD_ID}/onboarding")
    assert client.put_onboarding({}) is False
    assert client.put_onboarding({}) is False
