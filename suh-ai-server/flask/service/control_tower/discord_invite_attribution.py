"""초대 귀속 (폴러 틱마다 1회): 초대 사용 증가 확인 > 새 멤버 조회 > 한 프로젝트만 늘었으면 그 member 역할 부여
여러 프로젝트가 같은 틱에 늘면 귀속 불가 (부여 없음, 온보딩에서 직접 선택), 역할 제거 없음
실패 시 사용 횟수·확인 시각을 기록하지 않음 > 다음 틱 재시도 (이미 역할 받은 멤버는 건너뜀)"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from service.control_tower.discord_client import DiscordError, MEMBER_PAGE_MAXIMUM_LIMIT
from service.control_tower.discord_invites import MEMBER_ROLE_KIND
from service.control_tower.invite_store import ProjectInvite
from service.control_tower.meta_keys import META_KEY_INVITE_LAST_CHECKED_AT

logger = logging.getLogger(__name__)

# 멤버 목록 조회 최대 쪽 수 (쪽당 1000명)
MEMBER_LIST_MAXIMUM_PAGES = 20


class InviteAttributionStep:
    def __init__(self, client, store):
        self._client = client
        self._store = store

    def run(self, now: datetime) -> None:
        """귀속 1회 (예외 없음: 디스코드 실패·그 외 오류는 로그만)"""
        try:
            self._attribute(now)
        except DiscordError as error:
            logger.warning("[control-tower discord invite] attribution failed : status %s", error.status_code)
        except Exception as error:
            logger.warning("[control-tower discord invite] attribution crashed : %s", type(error).__name__)

    def _attribute(self, now: datetime) -> None:
        """초대 없음 > 생략 / 사용 증가 계산 > (증가 시) 역할 부여 > 사용 횟수 기록 > 확인 시각 = 틱 시작"""
        invites = self._store.all_project_invites()
        if not invites:
            return
        last_checked_at = self._last_checked_at(invites)
        uses_by_code = {str(invite.get("code")): int(invite.get("uses") or 0)
                        for invite in self._client.list_guild_invites()}
        # 디스코드에서 지워진 초대는 증가 0
        current_uses = {project_id: uses_by_code.get(invite.invite_code, invite.uses_seen)
                        for project_id, invite in invites.items()}
        joined_counts = {project_id: current_uses[project_id] - invite.uses_seen
                         for project_id, invite in invites.items() if current_uses[project_id] > invite.uses_seen}

        if len(joined_counts) == 1:
            project_id, joined_count = next(iter(joined_counts.items()))
            self._assign_project_role(project_id, joined_count, last_checked_at)
        elif len(joined_counts) > 1:
            logger.warning("[control-tower discord invite] ambiguous join : projects %s : no role assigned",
                           ",".join(sorted(joined_counts)))

        self._record_uses(invites, current_uses)
        self._store.set_meta(META_KEY_INVITE_LAST_CHECKED_AT, _to_utc_text(now))

    def _last_checked_at(self, invites: dict[str, ProjectInvite]) -> datetime:
        """meta 확인 시각 (없으면 가장 오래된 초대 생성 시각)"""
        recorded_text = self._store.get_meta(META_KEY_INVITE_LAST_CHECKED_AT)
        if recorded_text:
            return datetime.fromisoformat(recorded_text)
        return min(invite.created_at for invite in invites.values())

    def _assign_project_role(self, project_id: str, joined_count: int, last_checked_at: datetime) -> None:
        """확인 시각 이후 가입 + 봇 아님 + member 역할 없음 멤버 중 오래된 순 joined_count명에게 역할"""
        bindings = self._store.all_bindings()
        role_id = bindings.get((project_id, MEMBER_ROLE_KIND))
        if not role_id:
            logger.warning("[control-tower discord invite] skipped : project %s : member role not bound", project_id)
            return
        member_role_ids = {discord_id for (_, kind), discord_id in bindings.items() if kind == MEMBER_ROLE_KIND}
        candidates = sorted(
            (member for member in self._list_all_members()
             if _is_unassigned_new_member(member, member_role_ids, last_checked_at)),
            key=lambda member: _joined_at(member))
        for member in candidates[:joined_count]:
            self._client.add_member_role(member["user"]["id"], role_id)
        logger.info("[control-tower discord invite] assigned : project %s : joined %d, assigned %d",
                    project_id, joined_count, min(joined_count, len(candidates)))

    def _list_all_members(self) -> list[dict]:
        """멤버 전체 (user id 기준 쪽 넘김, 최대 20쪽)"""
        members: list[dict] = []
        after_user_id = None
        for _ in range(MEMBER_LIST_MAXIMUM_PAGES):
            page = self._client.list_members(after=after_user_id, limit=MEMBER_PAGE_MAXIMUM_LIMIT)
            members.extend(page)
            if len(page) < MEMBER_PAGE_MAXIMUM_LIMIT:
                break
            after_user_id = page[-1]["user"]["id"]
        return members

    def _record_uses(self, invites: dict[str, ProjectInvite], current_uses: dict[str, int]) -> None:
        """바뀐 사용 횟수만 기록"""
        for project_id, invite in invites.items():
            if current_uses[project_id] != invite.uses_seen:
                self._store.update_invite_uses_seen(project_id, invite.invite_code, current_uses[project_id])


def _is_unassigned_new_member(member: dict, member_role_ids: set[str], last_checked_at: datetime) -> bool:
    """귀속 대상: 봇 아님, 확인 시각 이후 가입, 어떤 프로젝트 member 역할도 없음"""
    user = member.get("user") or {}
    joined_at = _joined_at(member)
    if user.get("bot") or not user.get("id") or joined_at is None:
        return False
    if joined_at <= last_checked_at:
        return False
    return not member_role_ids.intersection(str(role_id) for role_id in member.get("roles") or ())


def _joined_at(member: dict) -> datetime | None:
    """디스코드 joined_at ISO > aware datetime (형식 오류 None)"""
    try:
        return datetime.fromisoformat(str(member.get("joined_at")))
    except ValueError:
        return None


def _to_utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")
