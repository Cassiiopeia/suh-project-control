"""디스코드 구조 동기화 공통 모델: 작업·결과 타입, 바인딩 kind·역할 참조 규칙, 디스코드 상수
"""
from __future__ import annotations

from dataclasses import dataclass, field

GLOBAL_SCOPE = "global"
# 프로젝트 카테고리 바인딩 kind
CATEGORY_KIND = "_category"
# 역할 바인딩 kind 접두사: role:member, role:dev, role:admin
ROLE_KIND_PREFIX = "role:"
ADMIN_ROLE_KEY = "admin"
EVERYONE_ROLE_KEY = "everyone"
# 관리자 역할 참조 (scope:role_key)
ADMIN_ROLE_REFERENCE = f"{GLOBAL_SCOPE}:{ADMIN_ROLE_KEY}"
# 디스코드 채널 타입: 0 텍스트, 4 카테고리
TEXT_CHANNEL_TYPE = 0
CATEGORY_CHANNEL_TYPE = 4
# 권한 덮어쓰기 대상 타입: 0 역할, 1 개인
ROLE_OVERWRITE_TYPE = 0
# VIEW_CHANNEL 권한 비트
VIEW_CHANNEL_PERMISSION = 1024
ARCHIVE_NAME_PREFIX = "[보관] "
PROJECT_NAME_PLACEHOLDER = "{project}"

# 작업 종류 (실행 순서: 역할 > 카테고리 > 채널 > 보관)
ACTION_CREATE_ROLE = "create_role"
ACTION_BIND = "bind"  # 이름으로 찾은 기존 객체 바인딩 기록만
ACTION_CREATE_CATEGORY = "create_category"
ACTION_CREATE_CHANNEL = "create_channel"
ACTION_UPDATE_CHANNEL = "update_channel"  # 카테고리 포함, 이름·관리 덮어쓰기 맞춤
ACTION_ARCHIVE_CATEGORY = "archive_category"
ACTION_ARCHIVE_CHANNEL = "archive_channel"  # 보관 카테고리 아래 채널 관리자만으로


@dataclass(frozen=True)
class SyncOperation:
    """동기화 작업 1건 (디스코드 id 대신 참조로 표현, 실행 시 실제 id로 변환)
    overwrites 항목: {"ref": "elum:member"|"global:admin"} 또는 {"id": 확정 id(@everyone=guild id)} + type·allow·deny(int)
    """
    action: str  # ACTION_* 중 하나
    scope: str  # 프로젝트 id 또는 'global' (바인딩 scope)
    kind: str | None  # 바인딩 kind: 'role:member', '_category', 채널 종류 / 바인딩 없는 보관 채널은 None
    name: str
    target_id: str | None = None  # 기존 디스코드 id (bind·update·archive)
    overwrites: tuple[dict, ...] = ()  # 관리 대상 덮어쓰기 (@everyone + 동기화가 관리하는 역할)
    parent_scope: str | None = None  # create_channel 부모 카테고리의 프로젝트 id (None = 최상위)
    preserved_overwrites: tuple[dict, ...] = ()  # 그대로 둘 기존 덮어쓰기 (개인·비관리 역할), 디스코드 원본 형태


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    archived: int = 0  # 보관 처리한 카테고리 + 하위 채널 수
    errors: list[str] = field(default_factory=list)
    is_onboarding_applied: bool = False


def role_reference(scope: str, role_key: str) -> str:
    """역할 참조 문자열: elum:member, global:admin"""
    return f"{scope}:{role_key}"


def role_binding_key(reference: str) -> tuple[str, str]:
    """역할 참조 > 바인딩 키: 'elum:member' > ('elum', 'role:member')"""
    scope, role_key = reference.split(":", 1)
    return scope, ROLE_KIND_PREFIX + role_key
