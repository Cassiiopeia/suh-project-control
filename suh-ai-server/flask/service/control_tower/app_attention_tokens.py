"""관제소 토큰 환경변수: 이름 규칙(pull·이벤트), 현재 값 읽기, 받은 토큰 검증(현재·이전 허용, 상수 시간 비교)
토큰 값은 반환만 하고 로그·응답·DB에 남기지 않음"""
from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

from config.control_tower_config import EVENT_TOKEN_ENV_PREFIX

# .env: 관제소 > 앱 수집 토큰 (CONTROL_PULL_TOKEN_<PROJECT>__<SOURCE>, 구분자 밑줄 2개)
PULL_TOKEN_ENV_PREFIX = "CONTROL_PULL_TOKEN_"
PULL_TOKEN_SEPARATOR = "__"
# 토큰 교체 중 이전 값 (예: CONTROL_EVENT_TOKEN_ELUM_PREVIOUS)
PREVIOUS_TOKEN_SUFFIX = "_PREVIOUS"


def to_env_id(identifier: str) -> str:
    """id > 환경변수 이름 조각 (대문자, '-' > '_')"""
    return identifier.upper().replace("-", "_")


def pull_token_env_name(project_id: str, source_id: str) -> str:
    """수집 토큰 환경변수 이름 (예: CONTROL_PULL_TOKEN_ELUM__API)"""
    return PULL_TOKEN_ENV_PREFIX + to_env_id(project_id) + PULL_TOKEN_SEPARATOR + to_env_id(source_id)


def event_token_env_name(project_id: str) -> str:
    """앱 > 관제소 이벤트·push 토큰 환경변수 이름 (예: CONTROL_EVENT_TOKEN_ELUM)"""
    return EVENT_TOKEN_ENV_PREFIX + to_env_id(project_id)


def read_pull_token(project_id: str, source_id: str) -> str | None:
    """수집 요청에 보낼 현재 토큰 (이전 값은 보내지 않음, 비어 있으면 None)"""
    return os.environ.get(pull_token_env_name(project_id, source_id)) or None


def is_pull_token_configured(project_id: str, source_id: str) -> bool:
    return read_pull_token(project_id, source_id) is not None


def _read_env_tokens(env_name: str, environ: Mapping[str, str]) -> list[str]:
    """현재·이전 토큰 중 값이 있는 것만"""
    env_tokens = [environ.get(name) for name in (env_name, env_name + PREVIOUS_TOKEN_SUFFIX)]
    return [token for token in env_tokens if token]


def is_env_token_configured(env_name: str, environ: Mapping[str, str] = os.environ) -> bool:
    """현재·이전 토큰 중 하나라도 있는지"""
    return bool(_read_env_tokens(env_name, environ))


def is_presented_token_valid(env_name: str, presented: str, environ: Mapping[str, str] = os.environ) -> bool:
    """받은 토큰 <-> 현재·이전 토큰 상수 시간 비교 (둘 다 없거나 받은 값이 비면 거부)"""
    expected_tokens = _read_env_tokens(env_name, environ)
    if not expected_tokens or not presented:
        return False
    presented_bytes = presented.encode("utf-8")
    # 후보 전부 비교 (어느 쪽과 맞았는지 시간 차이 안 남게)
    matches = [hmac.compare_digest(token.encode("utf-8"), presented_bytes) for token in expected_tokens]
    return any(matches)
