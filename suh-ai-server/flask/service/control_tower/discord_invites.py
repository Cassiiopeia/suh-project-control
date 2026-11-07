"""프로젝트 디스코드 초대 발급: 바인딩 확인 > (다시 만들기면 이전 초대 삭제) > status 채널 초대 생성 > 저장
초대로 들어온 멤버의 역할 부여는 discord_invite_attribution (폴러 틱)"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from service.control_tower.discord_client import DiscordError
from service.control_tower.discord_sync_models import ROLE_KIND_PREFIX
from service.control_tower.invite_store import ProjectInvite

logger = logging.getLogger(__name__)

# 초대가 가리키는 프로젝트 채널 종류 / 초대로 부여하는 역할 키
INVITE_CHANNEL_KIND = "status"
INVITE_ROLE_KEY = "member"
MEMBER_ROLE_KIND = ROLE_KIND_PREFIX + INVITE_ROLE_KEY
# 초대 만료 (초, 0 = 만료 없음) / 사용 횟수 상한 (0 = 무제한)
INVITE_MAX_AGE_SECONDS = 0
INVITE_MAX_USES = 0
# 디스코드 404 = 이미 없는 초대 (삭제 성공으로 봄)
STATUS_NOT_FOUND = 404
# 같은 프로젝트 초대 동시 생성 방지
INVITE_CREATE_LOCK = threading.Lock()


class InviteError(Exception):
    """초대 발급 실패: 응답 오류 코드 + HTTP 상태 (+ 디스코드 상태 코드)"""

    def __init__(self, code: str, status_code: int, discord_status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.discord_status_code = discord_status_code


def ensure_project_invite(client, store, project_id: str, should_regenerate: bool, now: datetime) -> ProjectInvite:
    """있으면 그대로 반환, 없거나 다시 만들기면 새로 발급 (디스코드 동기화 전이면 InviteError 409)"""
    with INVITE_CREATE_LOCK:
        existing = store.get_project_invite(project_id)
        if existing is not None and not should_regenerate:
            return existing
        channel_id = store.get_binding(project_id, INVITE_CHANNEL_KIND)
        if not channel_id or not store.get_binding(project_id, MEMBER_ROLE_KIND):
            raise InviteError("discord_not_synced", 409)
        if existing is not None:
            _delete_previous_invite(client, existing)
        try:
            created = client.create_invite(channel_id, max_age=INVITE_MAX_AGE_SECONDS,
                                           max_uses=INVITE_MAX_USES, unique=True)
        except DiscordError as error:
            logger.warning("[control-tower discord invite] create failed : project %s : status %s",
                           project_id, error.status_code)
            raise InviteError("discord_failed", 502, error.status_code) from None
        invite = store.save_project_invite(project_id, created["code"], channel_id, now)
        logger.info("[control-tower discord invite] created : project %s : regenerated %s",
                    project_id, existing is not None)
        return invite


def _delete_previous_invite(client, existing: ProjectInvite) -> None:
    """이전 초대 삭제 (이미 없음 404는 성공, 그 외 실패는 새 초대 만들지 않음)"""
    try:
        client.delete_invite(existing.invite_code)
    except DiscordError as error:
        if error.status_code == STATUS_NOT_FOUND:
            return
        logger.warning("[control-tower discord invite] delete failed : project %s : status %s",
                       existing.project_id, error.status_code)
        raise InviteError("discord_failed", 502, error.status_code) from None
