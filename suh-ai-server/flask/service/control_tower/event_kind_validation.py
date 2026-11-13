"""관제소 사용자 정의 알림 종류 입력 검증: 요청 본문 > (EventKindSpec | None, 잘못된 칸 이름 목록)"""
from __future__ import annotations

import re

from service.control_tower.discord_sync_models import ROLE_KIND_PREFIX
from service.control_tower.registry_models import (
    RESERVED_EVENT_KINDS, DiscordPolicy, EventKindSpec, default_event_kind_visible_to, event_kind_visible_role_keys,
)

# 종류 이름: 소문자로 시작, 소문자·숫자·하이픈 2~32자 (관리 화면 안내 문구 = EVENT_KIND_RULE_TEXT)
EVENT_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
EVENT_KIND_RULE_TEXT = "소문자로 시작, 소문자·숫자·하이픈 2~32자"
# 채널 이름 길이 (글자 수)
CHANNEL_NAME_MIN_LENGTH = 1
CHANNEL_NAME_MAX_LENGTH = 40
# 종류가 잘못일 때 channel_name 검사를 통과시키는 자리표시 값
DEFAULT_CHANNEL_NAME_PLACEHOLDER = "-"


def parse_new_event_kind(payload: dict, discord: DiscordPolicy) -> tuple[EventKindSpec | None, list[str]]:
    """검증 > 기본값 채움 (channel_name = kind, visible_to = 기본 공개 대상) / 잘못된 칸 하나라도 있으면 (None, 칸 목록)
    discord: 실효 등록 정보의 디스코드 정책 (공개 대상 선택지 = discord.roles 역할 키)"""
    if not isinstance(payload, dict):
        return None, ["kind"]
    kind = payload.get("kind")
    # channel_name 생략 시 종류 이름 사용 (종류가 잘못이면 kind 오류만 보고)
    channel_name = payload.get("channel_name", kind if is_valid_event_kind(kind) else DEFAULT_CHANNEL_NAME_PLACEHOLDER)
    visible_to = payload.get("visible_to", list(default_event_kind_visible_to(discord)))

    invalid_fields = []
    if not is_valid_event_kind(kind):
        invalid_fields.append("kind")
    if not is_valid_channel_name(channel_name):
        invalid_fields.append("channel_name")
    if not is_valid_visible_to(visible_to, event_kind_visible_role_keys(discord)):
        invalid_fields.append("visible_to")
    if invalid_fields:
        return None, invalid_fields
    return EventKindSpec(kind, channel_name.strip(), tuple(visible_to)), []


def is_valid_event_kind(value) -> bool:
    """형식 일치 + 예약어·role: 접두 아님"""
    return (isinstance(value, str) and EVENT_KIND_PATTERN.fullmatch(value) is not None
            and value not in RESERVED_EVENT_KINDS and not value.startswith(ROLE_KIND_PREFIX))


def is_valid_channel_name(value) -> bool:
    """앞뒤 공백 제거 후 길이 확인 (공백만인 이름은 디스코드에서 빈 이름)"""
    return isinstance(value, str) and CHANNEL_NAME_MIN_LENGTH <= len(value.strip()) <= CHANNEL_NAME_MAX_LENGTH


def is_valid_visible_to(value, allowed_role_keys: tuple[str, ...]) -> bool:
    """허용 역할 키 부분집합 리스트, 중복 없음 (빈 리스트 = 관리자만)"""
    # 원소 검사 먼저 (리스트·딕셔너리 같은 해시 불가 값에서 set() 오류 방지)
    return (isinstance(value, list)
            and all(isinstance(role_key, str) and role_key in allowed_role_keys for role_key in value)
            and len(set(value)) == len(value))
