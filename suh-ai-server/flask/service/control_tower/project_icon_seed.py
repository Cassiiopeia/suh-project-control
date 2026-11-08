"""프로젝트 기본 썸네일 채우기: 등록 파일 icon_source_url > 저장된 썸네일이 없고 아직 안 가져온 프로젝트만 1회 가져와 저장
관리 화면에서 삭제한 뒤에도 다시 가져오지 않음 (가져오기 완료 표시), 실패는 표시 없이 남겨 다음 기동에 재시도"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from service.control_tower.project_icon_service import ProjectIconError, fetch_icon_bytes, normalize_icon
from service.control_tower.registry import Registry

logger = logging.getLogger(__name__)


def seed_default_project_icons(registry: Registry, store,
                               fetch_icon: Callable[[str], bytes] = fetch_icon_bytes) -> int:
    """대상 프로젝트 순회 > 가져오기 > 128px WebP 저장 > 완료 표시 (저장한 썸네일 수 반환)"""
    stored_icon_versions = store.load_project_icon_versions()
    saved_count = 0
    for project in registry.projects:
        if not project.icon_source_url or store.has_icon_seed_finished(project.id):
            continue
        if project.id in stored_icon_versions:  # 이미 관리 화면에서 올린 썸네일이 있음
            store.mark_icon_seed_finished(project.id)
            continue
        try:
            image_webp, content_hash = normalize_icon(fetch_icon(project.icon_source_url))
        except ProjectIconError as error:
            logger.warning("[control-tower icon seed] failed : %s : %s", project.id, error.code)
            continue
        store.save_project_icon(project.id, image_webp, content_hash, datetime.now(timezone.utc))
        store.mark_icon_seed_finished(project.id)
        saved_count += 1
        logger.info("[control-tower icon seed] saved : %s", project.id)
    return saved_count
