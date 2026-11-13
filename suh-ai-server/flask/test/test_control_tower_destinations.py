"""관제소 받을 곳: URL 암호화·표시용 힌트, 저장(원문 없음), dispatch 퍼뜨리기(프로젝트·종류·활성만), 실패 격리, 비밀값 없음"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from service import secret_cipher
from service.control_tower import destination_delivery
from service.control_tower.alert_planner import Notification
from service.control_tower.destination_delivery import (
    DestinationDeliverer, DestinationSecretNotConfiguredError, decrypt_destination_url, describe_url_hint,
    encrypt_destination_url, is_destination_url_supported,
)
from service.control_tower.event_dispatcher import EventDispatcher
from service.control_tower.store import ControlTowerStore

NOW = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
SECRET_ENVIRON = {"CONTROL_TOWER_SECRET": "tower-secret"}
OTHER_SECRET_ENVIRON = {"CONTROL_TOWER_SECRET": "other-secret"}
DISCORD_TOKEN = "webhook-token-value-ab12"
DISCORD_URL = f"discord://1234567890/{DISCORD_TOKEN}"
LOCAL_HOST = "127.0.0.1"


def _run_now(task, thread_name):
    task()


class _RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body_length = int(self.headers.get("Content-Length", 0))
        self.server.received_bodies.append((self.path, self.rfile.read(body_length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    # 테스트 속도: 반복 횟수만 낮춤 (알고리즘 동일)
    monkeypatch.setattr(secret_cipher, "PBKDF2_ITERATIONS", 1000)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


@pytest.fixture
def local_receiver():
    """127.0.0.1 임의 포트 HTTP 서버 (외부 네트워크 사용 안 함)"""
    server = HTTPServer((LOCAL_HOST, 0), _RecordingHandler)
    server.received_bodies = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


class FakeDiscordClient:
    def __init__(self):
        self.sent = []

    def send_embed(self, channel_id, embed):
        self.sent.append((channel_id, embed))
        return True


class FakeBindingStore:
    def get_binding(self, scope, kind):
        return f"channel-{scope}-{kind}"


def _notification(scope="elum", kind="report", **overrides) -> Notification:
    fields = dict(scope=scope, kind=kind, severity="warning", title="신고 접수", body="신고 123번", service_ids=(),
                  dedupe_key="", link_url="https://elum.example.com/reports/123", fields=(("사유", "스팸"),))
    fields.update(overrides)
    return Notification(**fields)


def _add_destination(store, project_id, kind, url, is_enabled=True, environ=SECRET_ENVIRON) -> int:
    url_encrypted, scheme = encrypt_destination_url(url, environ)
    destination_id = store.insert_destination(project_id, kind, f"{project_id} {kind}", url_encrypted, scheme,
                                              describe_url_hint(url), NOW)
    if not is_enabled:
        store.set_destination_enabled(destination_id, False)
    return destination_id


def _all_stored_text(store) -> str:
    connection = store._connection()
    table_names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    rows = [tuple(row) for name in table_names for row in connection.execute(f'SELECT * FROM "{name}"')]
    return repr(rows)


def _results_by_id(store) -> dict[int, str | None]:
    return {destination.destination_id: destination.last_result for destination in store.list_destinations()}


# ---- 암호화·힌트·지원 여부 ----

def test_encrypt_round_trip_with_same_secret():
    url_encrypted, scheme = encrypt_destination_url(DISCORD_URL, SECRET_ENVIRON)
    assert DISCORD_TOKEN.encode() not in url_encrypted
    assert decrypt_destination_url(url_encrypted, scheme, SECRET_ENVIRON) == DISCORD_URL


def test_decrypt_with_other_secret_fails():
    url_encrypted, scheme = encrypt_destination_url(DISCORD_URL, SECRET_ENVIRON)
    with pytest.raises(secret_cipher.SecretCipherError):
        decrypt_destination_url(url_encrypted, scheme, OTHER_SECRET_ENVIRON)


def test_encrypt_without_secret_raises():
    with pytest.raises(DestinationSecretNotConfiguredError):
        encrypt_destination_url(DISCORD_URL, {})


def test_url_hint_shows_scheme_and_last_four_only():
    assert describe_url_hint(DISCORD_URL) == "discord://…ab12"
    assert describe_url_hint("json://a") == "json://…"


def test_url_support_uses_vendored_apprise():
    assert is_destination_url_supported(DISCORD_URL)
    assert not is_destination_url_supported("nope://x")
    assert not is_destination_url_supported("")


# ---- 저장 ----

def test_store_keeps_no_plain_url(store):
    destination_id = _add_destination(store, "elum", "report", DISCORD_URL)
    stored_text = _all_stored_text(store)
    assert DISCORD_TOKEN not in stored_text and DISCORD_URL not in stored_text
    destination = store.list_destinations("elum")[0]
    assert destination.destination_id == destination_id and destination.url_hint == "discord://…ab12"
    assert destination.is_enabled and destination.last_result is None
    assert DISCORD_TOKEN not in repr(destination)


def test_store_enable_toggle_and_delete(store):
    destination_id = _add_destination(store, "elum", "report", DISCORD_URL)
    assert store.set_destination_enabled(destination_id, False)
    assert store.list_enabled_destinations("elum", "report") == []
    assert store.delete_destination(destination_id)
    assert not store.delete_destination(destination_id)
    assert not store.set_destination_enabled(destination_id, True)


# ---- dispatch 퍼뜨리기 ----

def test_dispatch_sends_only_to_enabled_destination_of_same_project_and_kind(store, local_receiver):
    port = local_receiver.server_address[1]
    target_id = _add_destination(store, "elum", "report", f"json://{LOCAL_HOST}:{port}/target")
    _add_destination(store, "elum", "report", f"json://{LOCAL_HOST}:{port}/disabled", is_enabled=False)
    _add_destination(store, "elum", "status", f"json://{LOCAL_HOST}:{port}/other-kind")
    _add_destination(store, "romrom", "report", f"json://{LOCAL_HOST}:{port}/other-project")
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=lambda: NOW)
    discord_client = FakeDiscordClient()
    dispatcher = EventDispatcher(FakeBindingStore(), lambda: discord_client, "https://status.example.com",
                                 destination_deliverer=deliverer)

    assert dispatcher.dispatch(_notification()) is True

    assert [path for path, _ in local_receiver.received_bodies] == ["/target"]
    payload = json.loads(local_receiver.received_bodies[0][1])
    assert payload["title"] == "신고 접수"
    assert payload["message"] == "신고 123번\n\n사유: 스팸\n\nhttps://elum.example.com/reports/123"
    assert len(discord_client.sent) == 1
    destination = next(item for item in store.list_destinations("elum") if item.destination_id == target_id)
    assert destination.last_result == "sent" and destination.last_sent_at == NOW


def test_info_event_is_delivered_to_status_destinations(store, monkeypatch):
    status_id = _add_destination(store, "elum", "status", DISCORD_URL)
    _add_destination(store, "elum", "info", DISCORD_URL)
    sent_urls = []
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: sent_urls.append(url)
                        or True)
    DestinationDeliverer(store, _run_now, SECRET_ENVIRON).deliver(_notification(kind="info"))
    assert sent_urls == [DISCORD_URL]
    assert _results_by_id(store)[status_id] == "sent"


def test_global_notification_is_not_delivered(store):
    _add_destination(store, "global", "alert", DISCORD_URL)
    run_calls = []
    DestinationDeliverer(store, lambda task, thread_name: run_calls.append(thread_name), SECRET_ENVIRON).deliver(
        _notification(scope="global", kind="alert"))
    assert run_calls == []


def test_destinations_are_delivered_without_discord_client(store, monkeypatch):
    _add_destination(store, "elum", "report", DISCORD_URL)
    sent_urls = []
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: sent_urls.append(url)
                        or True)
    dispatcher = EventDispatcher(FakeBindingStore(), lambda: None, "https://status.example.com",
                                 destination_deliverer=DestinationDeliverer(store, _run_now, SECRET_ENVIRON))
    assert dispatcher.dispatch(_notification()) is False
    assert sent_urls == [DISCORD_URL]


# ---- 실패 격리 ----

def test_destination_error_keeps_default_send_and_records_type_only(store, monkeypatch, caplog):
    failing_id = _add_destination(store, "elum", "report", DISCORD_URL)
    working_id = _add_destination(store, "elum", "report", "discord://222/second-token")

    def send_or_raise(url, title, body):
        if url == DISCORD_URL:
            raise RuntimeError(f"boom {url}")
        return True

    monkeypatch.setattr(destination_delivery, "_send_with_apprise", send_or_raise)
    discord_client = FakeDiscordClient()
    dispatcher = EventDispatcher(FakeBindingStore(), lambda: discord_client, "https://status.example.com",
                                 destination_deliverer=DestinationDeliverer(store, _run_now, SECRET_ENVIRON))
    with caplog.at_level(logging.DEBUG):
        assert dispatcher.dispatch(_notification()) is True

    results = _results_by_id(store)
    assert results[failing_id] == "error:RuntimeError" and results[working_id] == "sent"
    assert DISCORD_TOKEN not in _all_stored_text(store)
    assert DISCORD_TOKEN not in caplog.text and "second-token" not in caplog.text


def test_failed_send_is_recorded(store, monkeypatch):
    destination_id = _add_destination(store, "elum", "report", DISCORD_URL)
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: False)
    DestinationDeliverer(store, _run_now, SECRET_ENVIRON).deliver(_notification())
    assert _results_by_id(store)[destination_id] == "failed"


def test_deliverer_exception_does_not_break_dispatch():
    class BrokenDeliverer:
        def deliver(self, notification):
            raise RuntimeError("deliverer broken")

    discord_client = FakeDiscordClient()
    dispatcher = EventDispatcher(FakeBindingStore(), lambda: discord_client, "https://status.example.com",
                                 destination_deliverer=BrokenDeliverer())
    assert dispatcher.dispatch(_notification()) is True


def test_apprise_logs_do_not_leak_url(store, caplog):
    # 닫힌 포트로 실제 Apprise 발송 실패 > Apprise 자체 로그에 URL이 섞여도 우리 로그로 나오지 않음
    destination_id = _add_destination(store, "elum", "report", f"json://{LOCAL_HOST}:1/leak-marker-token")
    with caplog.at_level(logging.DEBUG):
        DestinationDeliverer(store, _run_now, SECRET_ENVIRON).deliver(_notification())
    assert _results_by_id(store)[destination_id] == "failed"
    assert "leak-marker-token" not in caplog.text


# ---- 비밀값 없음 ----

def test_missing_secret_skips_delivery_with_throttled_warning(store, monkeypatch, caplog):
    destination_id = _add_destination(store, "elum", "report", DISCORD_URL)
    sent_urls = []
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: sent_urls.append(url)
                        or True)
    deliverer = DestinationDeliverer(store, _run_now, {})
    with caplog.at_level(logging.WARNING):
        deliverer.deliver(_notification())
        deliverer.deliver(_notification())
    assert sent_urls == []
    assert _results_by_id(store)[destination_id] == "skipped:secret_missing"
    warnings = [record for record in caplog.records if "CONTROL_TOWER_SECRET" in record.getMessage()]
    assert len(warnings) == 1


def test_changed_secret_records_decrypt_failure(store, monkeypatch):
    destination_id = _add_destination(store, "elum", "report", DISCORD_URL)
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: True)
    DestinationDeliverer(store, _run_now, OTHER_SECRET_ENVIRON).deliver(_notification())
    assert _results_by_id(store)[destination_id] == "skipped:decrypt_failed"
