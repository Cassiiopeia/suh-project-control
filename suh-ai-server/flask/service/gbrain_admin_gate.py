"""
gbrain /admin 게이트 쿠키: 발급, 검사
값 형식: {만료 epoch 초}.{HMAC-SHA256(관리자 토큰, "gbrain-admin-gate|{만료}") hex}
관리자 토큰을 HMAC 키로 씀 > 별도 비밀값 없음, 토큰 교체 시 기존 쿠키 전부 무효
"""
import hashlib
import hmac
import time

GATE_SIGNING_PREFIX = 'gbrain-admin-gate|'


def _sign(admin_token: str, expires_epoch_seconds: int) -> str:
    message = f'{GATE_SIGNING_PREFIX}{expires_epoch_seconds}'.encode('utf-8')
    return hmac.new(admin_token.encode('utf-8'), message, hashlib.sha256).hexdigest()


def create_gate_cookie_value(admin_token: str, valid_seconds: int, now_epoch_seconds=None) -> str:
    now_epoch_seconds = int(time.time()) if now_epoch_seconds is None else int(now_epoch_seconds)
    expires_epoch_seconds = now_epoch_seconds + int(valid_seconds)
    return f'{expires_epoch_seconds}.{_sign(admin_token, expires_epoch_seconds)}'


def is_gate_cookie_valid(admin_token, cookie_value, now_epoch_seconds=None) -> bool:
    """서명 일치 + 만료 전 (토큰·쿠키 없거나 형식 틀리면 False)"""
    if not admin_token or not cookie_value or '.' not in cookie_value:
        return False
    expires_text, signature = cookie_value.split('.', 1)
    if not expires_text.isdigit():
        return False
    expires_epoch_seconds = int(expires_text)
    now_epoch_seconds = int(time.time()) if now_epoch_seconds is None else int(now_epoch_seconds)
    if expires_epoch_seconds <= now_epoch_seconds:
        return False
    return hmac.compare_digest(signature, _sign(admin_token, expires_epoch_seconds))
