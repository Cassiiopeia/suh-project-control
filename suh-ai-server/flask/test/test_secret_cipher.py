"""test_secret_cipher.py — 비밀 문자열(앱 비밀번호 예시) 암호화 왕복·비밀 문구 불일치·salt 행별 상이"""
import pytest

from service import secret_cipher as cipher

SECRET = 'test-secret-phrase'
APP_PASSWORD = 'abcdefghijklmnop'


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    # 테스트 속도: 반복 횟수만 낮춤 (알고리즘 동일)
    monkeypatch.setattr(cipher, 'PBKDF2_ITERATIONS', 1000)


def test_round_trip_returns_original():
    encrypted = cipher.encrypt_secret_text(APP_PASSWORD, SECRET)
    assert cipher.decrypt_secret_text(encrypted, cipher.ENCRYPTION_SCHEME, SECRET) == APP_PASSWORD


def test_ciphertext_has_no_plaintext_and_differs_each_time():
    first = cipher.encrypt_secret_text(APP_PASSWORD, SECRET)
    second = cipher.encrypt_secret_text(APP_PASSWORD, SECRET)
    assert APP_PASSWORD.encode() not in first
    assert first != second
    assert first[:cipher.SALT_BYTES] != second[:cipher.SALT_BYTES]


def test_wrong_secret_fails():
    encrypted = cipher.encrypt_secret_text(APP_PASSWORD, SECRET)
    with pytest.raises(cipher.SecretCipherError):
        cipher.decrypt_secret_text(encrypted, cipher.ENCRYPTION_SCHEME, 'other-secret')


def test_unknown_scheme_fails():
    encrypted = cipher.encrypt_secret_text(APP_PASSWORD, SECRET)
    with pytest.raises(cipher.SecretCipherError):
        cipher.decrypt_secret_text(encrypted, 'dpapi', SECRET)


def test_missing_secret_fails():
    with pytest.raises(cipher.SecretCipherError):
        cipher.encrypt_secret_text(APP_PASSWORD, '')


def test_decrypt_accepts_memoryview_from_db():
    # psycopg2 BYTEA 조회 결과는 memoryview
    encrypted = cipher.encrypt_secret_text(APP_PASSWORD, SECRET)
    assert cipher.decrypt_secret_text(memoryview(encrypted), cipher.ENCRYPTION_SCHEME, SECRET) == APP_PASSWORD
