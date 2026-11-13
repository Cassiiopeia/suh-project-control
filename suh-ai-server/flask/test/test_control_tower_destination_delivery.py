"""관제소 받을 곳 발송: dispatch 퍼뜨리기(프로젝트·종류·활성만), 실패 격리, 비밀값 없음, 복호화 캐시·손상된 암호문"""
from __future__ import annotations

import json
import logging

from control_tower_destination_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    DISCORD_TOKEN, DISCORD_URL, LOCAL_HOST, NOW, OTHER_SECRET_ENVIRON, SECRET_ENVIRON, FakeBindingStore,
    FakeDiscordClient, _add_destination, _all_stored_text, _notification, _results_by_id, _run_now, fast_kdf,
    local_receiver, store,
)
from service import secret_cipher
from service.control_tower import destination_delivery
from service.control_tower.destination_delivery import DestinationDeliverer, encrypt_destination_url
from service.control_tower.event_dispatcher import EventDispatcher


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


# ---- 복호화 캐시·손상된 암호문 ----

def _count_decrypt_calls(monkeypatch) -> list[int]:
    decrypt_calls = []
    original_decrypt = destination_delivery.decrypt_secret_text

    def counting_decrypt(*arguments):
        decrypt_calls.append(1)
        return original_decrypt(*arguments)

    monkeypatch.setattr(destination_delivery, "decrypt_secret_text", counting_decrypt)
    return decrypt_calls


def test_second_delivery_reuses_decrypted_url(store, monkeypatch):
    _add_destination(store, "elum", "report", DISCORD_URL)
    decrypt_calls = _count_decrypt_calls(monkeypatch)
    sent_urls = []
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: sent_urls.append(url)
                        or True)
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON)
    deliverer.deliver(_notification(dedupe_key="report:1"))
    deliverer.deliver(_notification(dedupe_key="report:2"))
    assert sent_urls == [DISCORD_URL, DISCORD_URL]
    assert len(decrypt_calls) == 1
    assert DISCORD_TOKEN not in repr(deliverer.__dict__)


def test_changed_blob_is_decrypted_again(store, monkeypatch):
    destination_id = _add_destination(store, "elum", "report", DISCORD_URL)
    decrypt_calls = _count_decrypt_calls(monkeypatch)
    sent_urls = []
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: sent_urls.append(url)
                        or True)
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON)
    deliverer.deliver(_notification(dedupe_key="report:1"))
    new_url = "discord://999/replaced-token"
    new_blob, _ = encrypt_destination_url(new_url, SECRET_ENVIRON)
    with store._connection() as connection:
        connection.execute("UPDATE project_event_destination SET url_encrypted = ? WHERE destination_id = ?",
                           (new_blob, destination_id))
    deliverer.deliver(_notification(dedupe_key="report:2"))
    assert sent_urls == [DISCORD_URL, new_url]
    assert len(decrypt_calls) == 2


def test_malformed_blob_records_decrypt_failure(store, monkeypatch):
    destination_id = store.insert_destination("elum", "report", "broken", b"short", secret_cipher.ENCRYPTION_SCHEME,
                                              "discord://…", NOW)
    monkeypatch.setattr(destination_delivery, "_send_with_apprise", lambda url, title, body: True)
    DestinationDeliverer(store, _run_now, SECRET_ENVIRON).deliver(_notification())
    assert _results_by_id(store)[destination_id] == "skipped:decrypt_failed"
