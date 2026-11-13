"""관제소 프로젝트 이벤트 토큰: 발급·교체·폐기, 받은 토큰 검증(이벤트·push 입구 공용), 설정 상태 설명
DB 관리 프로젝트 = DB 토큰(현재·만료 전 이전)만 인정, 아니면 환경변수 토큰 경로. 원문은 발급 응답 1번만 반환"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta
from time import monotonic

from config.control_tower_config import CONTROL_TOWER_SECRET_ENV, PREVIOUS_EVENT_TOKEN_VALID_DAYS
from service.control_tower.app_attention_tokens import (
    event_token_env_name, is_env_token_configured, is_presented_token_valid,
)
from service.control_tower.utc_text import to_utc_text

logger = logging.getLogger(__name__)

# 해시 키 파생 접두사: SHA256(접두사 + 비밀값) = HMAC 키 (다른 용도 키와 분리)
TOKEN_HASH_KEY_PREFIX = "control-tower:event-token:"
# 발급 토큰 난수 크기 (바이트, urlsafe 43자)
TOKEN_RANDOM_BYTES = 32
PREVIOUS_TOKEN_VALID_PERIOD = timedelta(days=PREVIOUS_EVENT_TOKEN_VALID_DAYS)
# 비밀값 없음 경고 최소 간격 (초, 프로세스당, 미인증 요청 반복 시 로그 폭주 방지)
SECRET_MISSING_WARNING_INTERVAL_SECONDS = 600

_secret_missing_warning_lock = threading.Lock()
_last_secret_missing_warning_monotonic: float | None = None


class TokenSecretNotConfiguredError(Exception):
    """CONTROL_TOWER_SECRET 없음 > 발급·교체 불가"""


def _read_token_secret(environ: Mapping[str, str]) -> str | None:
    return environ.get(CONTROL_TOWER_SECRET_ENV) or None


def is_token_secret_configured(environ: Mapping[str, str] = os.environ) -> bool:
    return _read_token_secret(environ) is not None


def _hash_token(token: str, secret: str) -> str:
    """토큰 > HMAC-SHA256(key=SHA256(접두사 + 비밀값)) hex"""
    hash_key = hashlib.sha256((TOKEN_HASH_KEY_PREFIX + secret).encode("utf-8")).digest()
    return hmac.new(hash_key, token.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_project_token(store, project_id: str, now: datetime, environ: Mapping[str, str] = os.environ) -> str:
    """새 토큰 발급: 비밀값 확인 > 난수 생성 > 해시 저장(기존 현재는 유예 기간 동안 이전으로) > 원문 반환"""
    secret = _read_token_secret(environ)
    if secret is None:
        raise TokenSecretNotConfiguredError(CONTROL_TOWER_SECRET_ENV)
    token = secrets.token_urlsafe(TOKEN_RANDOM_BYTES)
    store.rotate_project_token(project_id, _hash_token(token, secret), now, now + PREVIOUS_TOKEN_VALID_PERIOD)
    logger.info("[control-tower event-token] issued : project=%s", project_id)
    return token


def revoke_project_tokens(store, project_id: str) -> bool:
    """현재·이전 토큰 삭제 (DB 관리 유지 = 환경변수 토큰으로 되돌아가지 않음) > 지운 토큰이 있었는지"""
    is_deleted = store.delete_project_tokens(project_id)
    if is_deleted:
        logger.info("[control-tower event-token] revoked : project=%s", project_id)
    else:
        logger.info("[control-tower event-token] revoke skipped : no tokens project=%s", project_id)
    return is_deleted


def _should_warn_secret_missing() -> bool:
    """비밀값 없음 경고 허용 여부 (마지막 경고 후 최소 간격 경과, 스레드 안전)"""
    global _last_secret_missing_warning_monotonic
    current_monotonic = monotonic()
    with _secret_missing_warning_lock:
        last_monotonic = _last_secret_missing_warning_monotonic
        if last_monotonic is not None and current_monotonic - last_monotonic < SECRET_MISSING_WARNING_INTERVAL_SECONDS:
            return False
        _last_secret_missing_warning_monotonic = current_monotonic
        return True


def is_project_token_valid(store, project_id: str, presented: str, now: datetime,
                           environ: Mapping[str, str] = os.environ) -> bool:
    """받은 토큰 검증: 빈 값 거부 > DB 관리 아니면 환경변수 경로 > 비밀값 없으면 거부 > 유효 해시 전부 상수 시간 비교"""
    if not presented:
        return False
    state = store.load_project_token_state(project_id)
    if not state.is_db_managed:
        return is_presented_token_valid(event_token_env_name(project_id), presented, environ)
    secret = _read_token_secret(environ)
    if secret is None:
        if _should_warn_secret_missing():
            logger.warning("[control-tower event-token] rejected : %s not configured project=%s",
                           CONTROL_TOWER_SECRET_ENV, project_id)
        return False
    presented_hash = _hash_token(presented, secret)
    # 후보 전부 비교 (어느 쪽과 맞았는지 시간 차이 안 남게), 만료된 이전 토큰 제외
    matches = [hmac.compare_digest(token_hash, presented_hash)
               for token_hash, expires_at in state.token_hashes if expires_at is None or expires_at > now]
    return any(matches)


def is_project_token_configured(store, project_id: str, environ: Mapping[str, str] = os.environ) -> bool:
    """입구에서 통과 가능한 토큰이 있는지: DB 관리면 현재 토큰, 아니면 환경변수 현재·이전"""
    state = store.load_project_token_state(project_id)
    if state.is_db_managed:
        return state.current_created_at is not None
    return is_env_token_configured(event_token_env_name(project_id), environ)


def describe_project_token(store, project_id: str, now: datetime, environ: Mapping[str, str] = os.environ) -> dict:
    """관리 화면용 토큰 상태 (토큰·해시 값 없음, 만료된 이전은 has_previous False)"""
    state = store.load_project_token_state(project_id)
    has_previous = state.previous_expires_at is not None and state.previous_expires_at > now
    return {
        "is_db_managed": state.is_db_managed,
        "has_current": state.current_created_at is not None,
        "current_created_at": to_utc_text(state.current_created_at) if state.current_created_at else None,
        "has_previous": has_previous,
        "previous_expires_at": to_utc_text(state.previous_expires_at) if has_previous else None,
        "is_env_configured": is_env_token_configured(event_token_env_name(project_id), environ),
    }
