"""디스코드 구조 동기화 공개 진입점: 현재 조회 > 계획 > 실행 > 온보딩 질문 (다른 모듈은 여기서만 import)
등록 파일이 원본, 삭제 없음 (빠진 프로젝트는 보관)
"""
from __future__ import annotations

import hashlib
import json
import logging

from service.control_tower.discord_client import DiscordError
from service.control_tower.discord_sync_apply import apply_sync
from service.control_tower.discord_sync_models import GLOBAL_SCOPE, ROLE_KIND_PREFIX, SyncOperation, SyncReport
from service.control_tower.discord_sync_plan import plan_sync
from service.control_tower.registry import Registry

__all__ = ["SyncOperation", "SyncReport", "apply_sync", "build_onboarding_payload", "plan_sync", "sync_discord"]

logger = logging.getLogger(__name__)

ONBOARDING_PROMPT_TITLE = "어떤 프로젝트 알림을 받을까요?"
ONBOARDING_OPTION_DESCRIPTION = "{project_name} 상태·배포 알림"
# 온보딩에서 고르는 역할 키
ONBOARDING_ROLE_KEY = "member"
# 온보딩 옵션에서 빼는 프로젝트 (관리자 전용 인프라)
ONBOARDING_EXCLUDED_PROJECT_IDS = ("infra",)
# 온보딩 질문 타입: 0 객관식 / 온보딩 모드: 0 기본
ONBOARDING_PROMPT_TYPE_MULTIPLE_CHOICE = 0
ONBOARDING_MODE_DEFAULT = 0
NOTICE_CHANNEL_KIND = "notice"
# meta: 마지막으로 성공한 온보딩 PUT payload의 sha256 (같으면 PUT 생략)
META_KEY_ONBOARDING_HASH = "discord_onboarding_hash"


def sync_discord(registry: Registry, client, store, guild_id: str) -> SyncReport:
    """동기화 1회: 현재 채널·역할 조회 > 계획 > 실행 > 온보딩 (조회 실패 시 오류만 담아 반환)"""
    try:
        current_channels = client.list_channels()
        current_roles = client.list_roles()
    except DiscordError as error:
        logger.warning("[control-tower discord sync] listing failed : status %s", error.status_code)
        return SyncReport(errors=[f"list: status {error.status_code} {error.reason}".rstrip()])

    operations = plan_sync(registry, current_channels, current_roles, guild_id, store.all_bindings())
    report = apply_sync(client, store, operations)
    report.is_onboarding_applied = _apply_onboarding(registry, client, store)
    logger.info("[control-tower discord sync] done : created %d, updated %d, archived %d, errors %d, onboarding %s",
                report.created, report.updated, report.archived, len(report.errors), report.is_onboarding_applied)
    return report


def build_onboarding_payload(registry: Registry, role_ids_by_project: dict[str, str],
                             notice_channel_id: str | None = None) -> dict:
    """온보딩 질문 1개: 프로젝트마다 옵션 1개(member 역할 부여), 역할 없는 프로젝트·인프라 제외"""
    options = [
        {
            "title": project.name,
            "description": ONBOARDING_OPTION_DESCRIPTION.format(project_name=project.name),
            "role_ids": [role_ids_by_project[project.id]],
            "channel_ids": [],
        }
        for project in registry.projects
        if project.id not in ONBOARDING_EXCLUDED_PROJECT_IDS and role_ids_by_project.get(project.id)
    ]
    return {
        "prompts": [{
            "type": ONBOARDING_PROMPT_TYPE_MULTIPLE_CHOICE,
            "title": ONBOARDING_PROMPT_TITLE,
            "single_select": False,
            "required": False,
            "in_onboarding": True,
            "options": options,
        }],
        "default_channel_ids": [notice_channel_id] if notice_channel_id else [],
        "enabled": True,
        "mode": ONBOARDING_MODE_DEFAULT,
    }


def _apply_onboarding(registry: Registry, client, store) -> bool:
    """바인딩된 member 역할·공지 채널로 온보딩 PUT: 마지막 성공과 같으면 생략(True), 옵션 없으면 생략(False)
    성공 시에만 해시 기록 > 실패 뒤 다음 동기화에서 재시도"""
    bindings = store.all_bindings()
    role_ids_by_project = {
        project.id: bindings[(project.id, ROLE_KIND_PREFIX + ONBOARDING_ROLE_KEY)]
        for project in registry.projects
        if (project.id, ROLE_KIND_PREFIX + ONBOARDING_ROLE_KEY) in bindings
    }
    payload = build_onboarding_payload(registry, role_ids_by_project, bindings.get((GLOBAL_SCOPE, NOTICE_CHANNEL_KIND)))
    if not payload["prompts"][0]["options"]:
        return False
    payload_hash = _onboarding_payload_hash(payload)
    if store.get_meta(META_KEY_ONBOARDING_HASH) == payload_hash:
        return True
    if not client.put_onboarding(payload):
        return False
    store.set_meta(META_KEY_ONBOARDING_HASH, payload_hash)
    return True


def _onboarding_payload_hash(payload: dict) -> str:
    """정규화 JSON(키 정렬)의 sha256"""
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
