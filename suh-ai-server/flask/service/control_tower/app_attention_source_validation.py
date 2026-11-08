"""앱 확인할 일 관리 API 입력 검증: 소스 추가·수정(주소, 방식, 주기·timeout·끊김 판정), 항목 덮어쓰기
결과는 (저장할 값, 잘못된 칸 이름 목록). 수정은 기존 값과 합친 뒤 전체를 다시 검증"""
from __future__ import annotations

import ipaddress
import math
import re
from urllib.parse import urlsplit

from service.control_tower.app_attention_effective import ALERT_RULES, LEVEL_POLICIES
from service.control_tower.app_attention_models import (
    INTERVAL_SECONDS_DEFAULT, INTERVAL_SECONDS_MAX, INTERVAL_SECONDS_MIN, MAX_LABEL_LENGTH, MAX_URL_LENGTH,
    PUSH_ONLY_MIN_PERIOD_SECONDS, SOURCE_ID_MAX_LENGTH, SOURCE_ID_PATTERN, SOURCE_MODE_PULL, SOURCE_MODE_PUSH,
    SOURCE_MODES, STALE_AFTER_INTERVAL_MULTIPLIER, TIMEOUT_SECONDS_DEFAULT, TIMEOUT_SECONDS_MAX,
    TIMEOUT_SECONDS_MIN,
)
from service.control_tower.app_attention_store import AttentionSource
from service.control_tower.override_validation import is_valid_boolean, is_valid_identifier, parse_patch

# 끊김 판정 최대 (1일)
STALE_AFTER_SECONDS_MAX = 86400
# push 전용 기본 끊김 판정: 최소 전송 주기 x 2 (5분 주기 전송이 조금 늦어도 끊김으로 안 보이게)
PUSH_ONLY_STALE_AFTER_MULTIPLIER = 2
# http 주소를 허용하는 내부망 (그 외 http는 거부, https는 모든 호스트)
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(network)
                         for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"))
ENV_PLACEHOLDER_MARK = "${"
WHITESPACE_PATTERN = re.compile(r"\s")
# 항목 덮어쓰기 채널 종류 (프로젝트 채널 중 배포 제외)
OVERRIDE_CHANNEL_KINDS = ("attention", "status", "error", "report")
# 소스 칸: 추가 시 필수 2개 + 수정 가능 6개
SOURCE_KEY_FIELDS = ("project_id", "source_id")
SOURCE_SETTING_FIELDS = ("url", "is_enabled", "mode", "interval_seconds", "timeout_seconds", "stale_after_seconds")


def is_valid_source_id(value) -> bool:
    return isinstance(value, str) and len(value) <= SOURCE_ID_MAX_LENGTH and re.fullmatch(SOURCE_ID_PATTERN, value) \
        is not None


def is_valid_source_url(value) -> bool:
    """https 모든 호스트, http는 내부망 IPv4 또는 ${ENV} 치환 주소만 (2048자, 공백 없음)"""
    if not isinstance(value, str) or len(value) > MAX_URL_LENGTH or WHITESPACE_PATTERN.search(value):
        return False
    if value.startswith("https://"):
        return len(value) > len("https://")
    if not value.startswith("http://") or len(value) == len("http://"):
        return False
    return ENV_PLACEHOLDER_MARK in value or _is_private_ipv4_host(value)


def _is_private_ipv4_host(url: str) -> bool:
    try:
        address = ipaddress.IPv4Address(urlsplit(url).hostname or "")
    except ValueError:
        return False
    return any(address in network for network in PRIVATE_NETWORKS)


def _is_integer_in_range(value, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def default_stale_after_seconds(mode: str, interval_seconds: int) -> int:
    """끊김 판정 기본값: pull·both = interval x 5, push = max(interval x 5, 최소 전송 주기 x 2)"""
    stale_after_seconds = interval_seconds * STALE_AFTER_INTERVAL_MULTIPLIER
    if mode == SOURCE_MODE_PUSH:
        stale_after_seconds = max(stale_after_seconds, PUSH_ONLY_MIN_PERIOD_SECONDS * PUSH_ONLY_STALE_AFTER_MULTIPLIER)
    return stale_after_seconds


def parse_new_source(payload) -> tuple[dict, list[str]]:
    """POST 소스 검증: 필수 project_id·source_id·url(push는 선택), 나머지 기본값"""
    if not isinstance(payload, dict):
        return {}, ["body"]
    invalid_fields = [key for key in payload if key not in SOURCE_KEY_FIELDS + SOURCE_SETTING_FIELDS]
    if not is_valid_identifier(payload.get("project_id")):
        invalid_fields.append("project_id")
    if not is_valid_source_id(payload.get("source_id")):
        invalid_fields.append("source_id")
    settings = {name: payload.get(name) for name in SOURCE_SETTING_FIELDS}
    values, setting_invalid_fields = _resolve_settings(settings, is_stale_default=settings["stale_after_seconds"] is None)
    values.update(project_id=payload.get("project_id"), source_id=payload.get("source_id"))
    return values, invalid_fields + setting_invalid_fields


def parse_source_patch(payload, existing: AttentionSource) -> tuple[dict, list[str]]:
    """PATCH 소스 검증: 바꿀 칸만 받아 기존 값과 합침 > 전체 재검증 (stale_after_seconds null = 기본값)
    기존 끊김 판정이 기본값이었으면 주기·방식이 바뀔 때 기본값을 다시 계산"""
    if not isinstance(payload, dict) or not payload:
        return {}, ["body"]
    invalid_fields = [key for key in payload if key not in SOURCE_SETTING_FIELDS]
    settings = {name: getattr(existing, name) for name in SOURCE_SETTING_FIELDS}
    settings["url"] = existing.url or None
    was_stale_default = existing.stale_after_seconds == default_stale_after_seconds(existing.mode,
                                                                                    existing.interval_seconds)
    settings.update({key: value for key, value in payload.items() if key in SOURCE_SETTING_FIELDS})
    is_stale_default = payload.get("stale_after_seconds") is None and (
        "stale_after_seconds" in payload or was_stale_default)
    values, setting_invalid_fields = _resolve_settings(settings, is_stale_default)
    return values, invalid_fields + setting_invalid_fields


def _resolve_settings(settings: dict, is_stale_default: bool) -> tuple[dict, list[str]]:
    """설정 칸 기본값 채우기 > 칸별 검증 (url은 push면 선택, 끊김 판정은 주기 이상 1일 이하)"""
    mode = settings["mode"] if settings["mode"] is not None else SOURCE_MODE_PULL
    interval_seconds = settings["interval_seconds"] if settings["interval_seconds"] is not None \
        else INTERVAL_SECONDS_DEFAULT
    values = {
        "url": settings["url"],
        "is_enabled": settings["is_enabled"] if settings["is_enabled"] is not None else True,
        "mode": mode,
        "interval_seconds": interval_seconds,
        "timeout_seconds": settings["timeout_seconds"] if settings["timeout_seconds"] is not None
        else TIMEOUT_SECONDS_DEFAULT,
        "stale_after_seconds": settings["stale_after_seconds"],
    }
    invalid_fields = []
    if mode not in SOURCE_MODES:
        invalid_fields.append("mode")
    is_url_optional = mode == SOURCE_MODE_PUSH and values["url"] is None
    if not is_url_optional and not is_valid_source_url(values["url"]):
        invalid_fields.append("url")
    if not is_valid_boolean(values["is_enabled"]):
        invalid_fields.append("is_enabled")
    if not _is_integer_in_range(interval_seconds, INTERVAL_SECONDS_MIN, INTERVAL_SECONDS_MAX):
        invalid_fields.append("interval_seconds")
    if not _is_integer_in_range(values["timeout_seconds"], TIMEOUT_SECONDS_MIN, TIMEOUT_SECONDS_MAX):
        invalid_fields.append("timeout_seconds")
    if invalid_fields:
        return values, invalid_fields

    # 끊김 판정: 기본값 계산 또는 범위 확인 (push 전용은 최소 전송 주기 이상)
    if is_stale_default:
        values["stale_after_seconds"] = default_stale_after_seconds(mode, interval_seconds)
    else:
        stale_minimum = max(interval_seconds, PUSH_ONLY_MIN_PERIOD_SECONDS if mode == SOURCE_MODE_PUSH else 0)
        if not _is_integer_in_range(values["stale_after_seconds"], stale_minimum, STALE_AFTER_SECONDS_MAX):
            invalid_fields.append("stale_after_seconds")
    return values, invalid_fields


# ---- 항목 덮어쓰기 ----

def _is_valid_override_label(value) -> bool:
    return isinstance(value, str) and 1 <= len(value.strip()) <= MAX_LABEL_LENGTH


def _is_valid_threshold(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# PATCH 칸 > 검사 함수 (null = 앱 값·기본 규칙으로)
ITEM_OVERRIDE_PATCH_VALIDATORS = {
    "is_hidden": is_valid_boolean,
    "label": _is_valid_override_label,
    "level_policy": lambda value: value in LEVEL_POLICIES,
    "alert_rule": lambda value: value in ALERT_RULES,
    "threshold": _is_valid_threshold,
    "channel_kind": lambda value: value in OVERRIDE_CHANNEL_KINDS,
}


def parse_item_override_patch(payload) -> tuple[dict, list[str]]:
    """PATCH 항목 덮어쓰기 검증: 6칸, null = 해제, label 앞뒤 공백 제거"""
    changes, invalid_fields = parse_patch(payload, ITEM_OVERRIDE_PATCH_VALIDATORS)
    if isinstance(changes.get("label"), str):
        changes["label"] = changes["label"].strip()
    if "threshold" in changes and changes["threshold"] is not None:
        changes["threshold"] = float(changes["threshold"])
    return changes, invalid_fields
