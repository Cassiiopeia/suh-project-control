"""관제소 관리 API 입력 검증: id·이름·주소·상태·순서·공지 > (바뀐 칸, 잘못된 칸 이름 목록)
PATCH 본문의 null = 덮어쓰기 지움 (허용 칸만), 모르는 키는 잘못된 칸으로 보고"""
from __future__ import annotations

import re

from service.control_tower.registry_models import NOTICE_LEVELS, SERVICE_STATUSES

# id: 소문자·숫자로 시작, 소문자·숫자·하이픈 2~41자
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
# 이름 길이 (글자 수)
NAME_MIN_LENGTH = 1
NAME_MAX_LENGTH = 60
# 외부 주소: http(s)://로 시작, 공백 없음, 2048자 이하
URL_PATTERN = re.compile(r"^https?://\S+$")
URL_MAX_LENGTH = 2048
# 표시 순서 범위 (작을수록 앞)
SORT_ORDER_MIN = 0
SORT_ORDER_MAX = 100000
# 공지 문구 최대 길이 (글자 수, 빈 문자열 = 공지 없음)
NOTICE_TEXT_MAX_LENGTH = 300


def is_valid_identifier(value) -> bool:
    return isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value) is not None


def is_valid_name(value) -> bool:
    return isinstance(value, str) and NAME_MIN_LENGTH <= len(value.strip()) <= NAME_MAX_LENGTH


def is_valid_url(value) -> bool:
    return isinstance(value, str) and len(value) <= URL_MAX_LENGTH and URL_PATTERN.fullmatch(value) is not None


def is_valid_status(value) -> bool:
    return value in SERVICE_STATUSES


def is_valid_boolean(value) -> bool:
    return isinstance(value, bool)


def is_valid_sort_order(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and SORT_ORDER_MIN <= value <= SORT_ORDER_MAX


def is_valid_notice_text(value) -> bool:
    return isinstance(value, str) and len(value) <= NOTICE_TEXT_MAX_LENGTH


def is_valid_notice_level(value) -> bool:
    return value in NOTICE_LEVELS


# PATCH 칸 > 검사 함수
SERVICE_PATCH_VALIDATORS = {
    "name": is_valid_name, "status": is_valid_status, "is_public": is_valid_boolean,
    "sort_order": is_valid_sort_order, "external_url": is_valid_url,
}
PROJECT_PATCH_VALIDATORS = {"name": is_valid_name, "is_hidden": is_valid_boolean, "sort_order": is_valid_sort_order}
STATUS_PAGE_PATCH_VALIDATORS = {
    "title": is_valid_name, "notice_text": is_valid_notice_text, "notice_level": is_valid_notice_level,
}
# 이름·제목은 앞뒤 공백 제거 후 저장
TRIMMED_FIELDS = ("name", "title", "notice_text")


def parse_patch(payload, validators: dict) -> tuple[dict, list[str]]:
    """PATCH 본문 검증: 객체 아님·빈 본문·모르는 키·잘못된 값 > 잘못된 칸 목록 (null은 지움으로 통과)"""
    if not isinstance(payload, dict) or not payload:
        return {}, ["body"]
    invalid_fields = [key for key in payload if key not in validators]
    changes = {}
    for key, value in payload.items():
        if key not in validators:
            continue
        if value is not None and not validators[key](value):
            invalid_fields.append(key)
            continue
        changes[key] = value.strip() if isinstance(value, str) and key in TRIMMED_FIELDS else value
    return changes, invalid_fields


def parse_new_service(payload) -> tuple[dict, list[str]]:
    """POST 서비스 검증: 필수 id·project_id·name·external_url, 선택 status(기본 active)·is_public(기본 false)"""
    payload = payload if isinstance(payload, dict) else {}
    checks = (("id", is_valid_identifier, True), ("project_id", is_valid_identifier, True),
              ("name", is_valid_name, True), ("external_url", is_valid_url, True),
              ("status", is_valid_status, False), ("is_public", is_valid_boolean, False))
    invalid_fields = [name for name, validator, is_required in checks
                      if (is_required or payload.get(name) is not None) and not validator(payload.get(name))]
    values = {
        "id": payload.get("id"), "project_id": payload.get("project_id"),
        "name": payload.get("name").strip() if isinstance(payload.get("name"), str) else None,
        "external_url": payload.get("external_url"),
        "status": payload.get("status") or "active", "is_public": payload.get("is_public") is True,
    }
    return values, invalid_fields


# 썸네일 업로드 본문 base64 최대 길이 (원본 2MB의 base64 여유분)
ICON_BASE64_MAX_LENGTH = 3_000_000


def parse_icon_request(payload) -> tuple[dict, list[str]]:
    """PUT 썸네일 검증: image_base64(파일 업로드) 또는 source_url(https 주소) 중 정확히 하나"""
    if not isinstance(payload, dict):
        return {}, ["body"]
    invalid_fields = [key for key in payload if key not in ("image_base64", "source_url")]
    provided_keys = [key for key in ("image_base64", "source_url") if payload.get(key) is not None]
    if len(provided_keys) != 1:
        return {}, invalid_fields + ["image_base64|source_url"]
    key = provided_keys[0]
    value = payload[key]
    is_valid = (isinstance(value, str) and 0 < len(value) <= ICON_BASE64_MAX_LENGTH) if key == "image_base64" else (
        is_valid_url(value) and value.startswith("https://"))
    if not is_valid:
        invalid_fields.append(key)
    return ({key: value} if not invalid_fields else {}), invalid_fields


def parse_new_project(payload) -> tuple[dict, list[str]]:
    """POST 프로젝트 검증: 필수 id·name"""
    payload = payload if isinstance(payload, dict) else {}
    invalid_fields = [name for name, validator in (("id", is_valid_identifier), ("name", is_valid_name))
                      if not validator(payload.get(name))]
    name = payload.get("name")
    return {"id": payload.get("id"), "name": name.strip() if isinstance(name, str) else None}, invalid_fields
