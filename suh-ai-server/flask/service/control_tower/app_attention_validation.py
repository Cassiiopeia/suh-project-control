"""attention v1 본문 검증: 최상위 검증 > 항목별 검증 > 스냅샷 (순수 함수, 저장·발송 없음)
최상위 위반 = 전체 거부, 항목 위반 = 그 항목만 버리고 사유 기록, 모르는 필드는 무시"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from service.control_tower.app_attention_models import (
    DEFAULT_ENVIRONMENT, ENVIRONMENTS, ITEM_KEY_PATTERN, ITEM_KIND_PATTERN, ITEM_LEVELS, ITEM_STATES,
    MAX_DESCRIPTION_LENGTH, MAX_DETAIL_LENGTH, MAX_GROUP_LENGTH, MAX_ITEM_COUNT, MAX_KEY_LENGTH,
    MAX_LABEL_LENGTH, MAX_UNIT_LENGTH, MAX_URL_LENGTH, SCHEMA_NAME, SUPPORTED_MAJOR_VERSION,
    TIMESTAMP_PATTERN, VERSION_PATTERN, AttentionItem, AttentionSnapshot,
)

ITEM_KEY_REGEX = re.compile(ITEM_KEY_PATTERN)
ITEM_KIND_REGEX = re.compile(ITEM_KIND_PATTERN)
VERSION_REGEX = re.compile(VERSION_PATTERN)
TIMESTAMP_REGEX = re.compile(TIMESTAMP_PATTERN)
# 절대 주소 기준 URL: https, 공백 없음
HTTPS_URL_REGEX = re.compile(r"^https://[^\s]+$")
# 소수초는 6자리까지만 파싱 (앱이 나노초를 보내도 허용)
FRACTION_REGEX = re.compile(r"\.([0-9]+)")
MICROSECOND_DIGITS = 6


@dataclass(frozen=True)
class ValidationResult:
    """검증 결과: 최상위 오류가 있으면 snapshot None, 항목 오류는 dropped_items (key 또는 #index, 사유)"""
    snapshot: AttentionSnapshot | None
    errors: tuple[str, ...]
    dropped_items: tuple[tuple[str, str], ...]


def parse_attention_snapshot(document: object) -> ValidationResult:
    """본문 검증: 최상위 오류 확인 > 항목별 검증(위반 항목 버림, key 중복은 뒤의 것 버림) > 스냅샷"""
    errors, header = _parse_header(document)
    if errors:
        return ValidationResult(None, tuple(errors), ())
    items, dropped_items = _parse_items(document["items"], header["admin_base_url"])
    snapshot = AttentionSnapshot(items=tuple(items), **header)
    return ValidationResult(snapshot, (), tuple(dropped_items))


def parse_utc_timestamp(text: object) -> datetime | None:
    """ISO 8601 문자열 > UTC datetime (형식 불량·없는 날짜는 None)"""
    if not isinstance(text, str) or TIMESTAMP_REGEX.fullmatch(text) is None:
        return None
    # 소수초 6자리로 맞춤, Z > +00:00
    normalized = FRACTION_REGEX.sub(lambda match: "." + match.group(1)[:MICROSECOND_DIGITS], text, count=1)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_header(document: object) -> tuple[list[str], dict]:
    """최상위 필드 검증 > (오류 목록, 스냅샷 머리글 값)"""
    if not isinstance(document, dict):
        return ["not_object"], {}
    errors: list[str] = []
    major_version = _parse_major_version(document.get("version"), errors)
    if document.get("schema") != SCHEMA_NAME:
        errors.append("invalid_schema")
    source = document.get("source")
    if not isinstance(source, dict):
        errors.append("invalid_source")
        source = {}
    app = source.get("app")
    if not isinstance(app, str) or not app:
        errors.append("invalid_source_app")
    app_version = source.get("app_version")
    if "app_version" in source and not isinstance(app_version, str):
        errors.append("invalid_source_app_version")
    environment = source.get("environment", DEFAULT_ENVIRONMENT)
    if environment not in ENVIRONMENTS:
        errors.append("invalid_source_environment")
    admin_base_url = source.get("admin_base_url")
    if "admin_base_url" in source and not _is_valid_base_url(admin_base_url):
        errors.append("invalid_source_admin_base_url")
    generated_at = parse_utc_timestamp(document.get("generated_at"))
    if generated_at is None:
        errors.append("invalid_generated_at")
    poll_after_seconds = _as_integer(document.get("poll_after_seconds"))
    if "poll_after_seconds" in document and (poll_after_seconds is None or poll_after_seconds < 0):
        errors.append("invalid_poll_after_seconds")
    items = document.get("items")
    if not isinstance(items, list):
        errors.append("invalid_items")
    elif len(items) > MAX_ITEM_COUNT:
        errors.append("too_many_items")
    if errors:
        return errors, {}
    return [], {
        "major_version": major_version, "app": app, "app_version": app_version, "environment": environment,
        "admin_base_url": admin_base_url, "generated_at": generated_at, "poll_after_seconds": poll_after_seconds,
    }


def _parse_major_version(version: object, errors: list[str]) -> int | None:
    """"주.부" > 주 버전 (형식 불량 invalid_version, 1 아님 unsupported_version)"""
    match = VERSION_REGEX.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        errors.append("invalid_version")
        return None
    major_version = int(match.group(1))
    if major_version != SUPPORTED_MAJOR_VERSION:
        errors.append("unsupported_version")
    return major_version


def _parse_items(raw_items: list, admin_base_url: str | None) -> tuple[list[AttentionItem], list[tuple[str, str]]]:
    """항목 순회: 위반 항목 버림 + key 중복은 뒤의 것 버림"""
    items: list[AttentionItem] = []
    dropped_items: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        item, reason = _parse_item(raw_item, admin_base_url)
        identifier = _describe_item(raw_item, index)
        if item is None:
            dropped_items.append((identifier, reason))
        elif item.key in seen_keys:
            dropped_items.append((identifier, "duplicate_key"))
        else:
            seen_keys.add(item.key)
            items.append(item)
    return items, dropped_items


def _describe_item(raw_item: object, index: int) -> str:
    """버린 항목의 표시 이름: 유효한 key 있으면 key, 아니면 #순번"""
    if isinstance(raw_item, dict) and _is_valid_key(raw_item.get("key")):
        return raw_item["key"]
    return f"#{index}"


def _parse_item(raw_item: object, admin_base_url: str | None) -> tuple[AttentionItem | None, str]:
    """항목 1건 검증 > (항목 또는 None, 버린 사유)"""
    if not isinstance(raw_item, dict):
        return None, "not_object"
    if not _is_valid_key(raw_item.get("key")):
        return None, "invalid_key"
    label = raw_item.get("label")
    if not (isinstance(label, str) and 1 <= len(label) <= MAX_LABEL_LENGTH and label.strip()):
        return None, "invalid_label"
    kind = raw_item.get("kind")
    if not (isinstance(kind, str) and ITEM_KIND_REGEX.fullmatch(kind)):
        return None, "invalid_kind"
    if raw_item.get("level") not in ITEM_LEVELS:
        return None, "invalid_level"
    common, reason = _parse_common_fields(raw_item, admin_base_url)
    if common is None:
        return None, reason
    kind_fields, reason = _parse_kind_fields(kind, raw_item)
    if kind_fields is None:
        return None, reason
    return AttentionItem(
        key=raw_item["key"], label=label, kind=kind, level=raw_item["level"], raw=dict(raw_item),
        **common, **kind_fields,
    ), ""


def _parse_common_fields(raw_item: dict, admin_base_url: str | None) -> tuple[dict | None, str]:
    """선택 공통 칸 검증 (있으면 형식 필수): group, description, detail, admin_url, latest_at"""
    text_limits = {"group": MAX_GROUP_LENGTH, "description": MAX_DESCRIPTION_LENGTH, "detail": MAX_DETAIL_LENGTH}
    fields: dict = {}
    for field_name, max_length in text_limits.items():
        value = raw_item.get(field_name)
        if field_name in raw_item and not (isinstance(value, str) and len(value) <= max_length):
            return None, f"invalid_{field_name}"
        fields[field_name] = value
    admin_url = raw_item.get("admin_url")
    if "admin_url" in raw_item and not (isinstance(admin_url, str) and len(admin_url) <= MAX_URL_LENGTH):
        return None, "invalid_admin_url"
    fields["admin_url"] = resolve_admin_url(admin_url, admin_base_url)
    latest_at = None
    if "latest_at" in raw_item:
        latest_at = parse_utc_timestamp(raw_item["latest_at"])
        if latest_at is None:
            return None, "invalid_latest_at"
    fields["latest_at"] = latest_at
    return fields, ""


def resolve_admin_url(admin_url: str | None, admin_base_url: str | None) -> str | None:
    """admin_url > 절대 https는 그대로, /상대경로는 기준 주소와 합침, 그 외(http, 형식 불량)는 None"""
    if not admin_url or re.search(r"\s", admin_url):
        return None
    if admin_url.startswith("https://") and len(admin_url) > len("https://"):
        return admin_url
    # "//host" 는 프로토콜 상대 주소라 제외
    if admin_url.startswith("/") and not admin_url.startswith("//") and admin_base_url:
        return admin_base_url.rstrip("/") + admin_url
    return None


def _parse_kind_fields(kind: str, raw_item: dict) -> tuple[dict | None, str]:
    """kind별 필수·선택 칸 (모르는 kind는 빈 칸으로 유지)"""
    if kind == "count":
        count = _as_integer(raw_item.get("count"))
        if count is None or count < 0:
            return None, "invalid_count"
        has_total = "total" in raw_item
        total = _as_integer(raw_item.get("total"))
        if has_total and (total is None or total < 0):
            return None, "invalid_total"
        return {"count": count, "total": total}, ""
    if kind == "gauge":
        return _parse_gauge_fields(raw_item)
    if kind == "state":
        if raw_item.get("state") not in ITEM_STATES:
            return None, "invalid_state"
        return {"state": raw_item["state"]}, ""
    return {}, ""


def _parse_gauge_fields(raw_item: dict) -> tuple[dict | None, str]:
    """gauge 칸: value(필수), limit(선택), unit(선택, 12자)"""
    value = _as_number(raw_item.get("value"))
    if value is None:
        return None, "invalid_value"
    limit = _as_number(raw_item.get("limit"))
    if "limit" in raw_item and limit is None:
        return None, "invalid_limit"
    unit = raw_item.get("unit")
    if "unit" in raw_item and not (isinstance(unit, str) and len(unit) <= MAX_UNIT_LENGTH):
        return None, "invalid_unit"
    return {"value": value, "limit": limit, "unit": unit}, ""


def _is_valid_key(key: object) -> bool:
    return isinstance(key, str) and len(key) <= MAX_KEY_LENGTH and ITEM_KEY_REGEX.fullmatch(key) is not None


def _is_valid_base_url(url: object) -> bool:
    return isinstance(url, str) and len(url) <= MAX_URL_LENGTH and HTTPS_URL_REGEX.fullmatch(url) is not None


def _as_integer(value: object) -> int | None:
    """정수 판정 (JSON 스키마와 같게 3.0도 정수, bool 제외)"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _as_number(value: object) -> float | None:
    """숫자 판정 (bool, NaN, 무한대 제외)"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None
