"""
Gmail 앱 비밀번호 암호화: 비밀 문구 > PBKDF2 키 > AES-256-GCM
저장 형식: salt(16) | nonce(12) | 암호문+태그, 플랫폼 독립 (Windows <-> Mac 이전 시 같은 비밀 문구로 복호화)
"""
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# DB encryption_scheme 값 (방식 교체 시 v2 추가)
ENCRYPTION_SCHEME = "pbkdf2-aes256gcm-v1"
SALT_BYTES = 16
NONCE_BYTES = 12
KEY_BYTES = 32
# PBKDF2-HMAC-SHA256 반복 횟수 (OWASP 2023 권장값)
PBKDF2_ITERATIONS = 600_000


class SecretCipherError(Exception):
    """비밀 문구 없음, 방식 불일치, 복호화 실패 (비밀 문구 변경·데이터 손상)"""


def encrypt_app_password(app_password: str, secret: str) -> bytes:
    """평문 앱 비밀번호 > salt | nonce | 암호문 (행마다 새 salt·nonce)"""
    if not secret:
        raise SecretCipherError("account secret not set")
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_derive_key(secret, salt)).encrypt(nonce, app_password.encode("utf-8"), None)
    return salt + nonce + ciphertext


def decrypt_app_password(encrypted: bytes, scheme: str, secret: str) -> str:
    """salt | nonce | 암호문 > 평문 앱 비밀번호"""
    if not secret:
        raise SecretCipherError("account secret not set")
    if scheme != ENCRYPTION_SCHEME:
        raise SecretCipherError(f"unknown encryption scheme: {scheme}")
    encrypted = bytes(encrypted)
    salt = encrypted[:SALT_BYTES]
    nonce = encrypted[SALT_BYTES:SALT_BYTES + NONCE_BYTES]
    ciphertext = encrypted[SALT_BYTES + NONCE_BYTES:]
    try:
        return AESGCM(_derive_key(secret, salt)).decrypt(nonce, ciphertext, None).decode("utf-8")
    except InvalidTag as error:
        raise SecretCipherError("decrypt failed: secret changed or data corrupted") from error


def _derive_key(secret: str, salt: bytes) -> bytes:
    """비밀 문구 + salt > 32바이트 AES 키"""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, iterations=PBKDF2_ITERATIONS)
    return kdf.derive(secret.encode("utf-8"))
