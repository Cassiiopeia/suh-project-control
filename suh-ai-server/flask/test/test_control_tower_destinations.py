"""관제소 받을 곳 URL 암호화·표시용 힌트·지원 여부, 저장(원문 없음)·사용 전환·삭제"""
from __future__ import annotations

import pytest

from control_tower_destination_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    DISCORD_TOKEN, DISCORD_URL, OTHER_SECRET_ENVIRON, SECRET_ENVIRON, _add_destination, _all_stored_text, fast_kdf,
    store,
)
from service import secret_cipher
from service.control_tower.destination_delivery import (
    DestinationSecretNotConfiguredError, decrypt_destination_url, describe_url_hint, encrypt_destination_url,
    is_destination_url_supported,
)


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
