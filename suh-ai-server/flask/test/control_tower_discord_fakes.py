"""관제소 디스코드 동기화 테스트 공통: 메모리 디스코드 서버(역할·채널·호출 기록), 등록 정보 생성"""
from __future__ import annotations

import copy
import re

from service.control_tower.discord_client import DiscordError
from service.control_tower.registry import DiscordPolicy, ProjectSpec, Registry
from service.control_tower.registry_models import DEFAULT_CHANNEL_VISIBILITY

GUILD_ID = "9000"
VIEW_CHANNEL = 1024
SEND_MESSAGES = 2048


def make_project(project_id: str, name: str, **visibility_overrides) -> ProjectSpec:
    """전역 기본 공개 대상 + 프로젝트 덮어쓰기 반영 (로더와 같은 병합 결과)"""
    return ProjectSpec(project_id, name, channel_visibility={**DEFAULT_CHANNEL_VISIBILITY, **visibility_overrides})


def make_registry(*projects: ProjectSpec, discord: DiscordPolicy | None = None) -> Registry:
    return Registry(projects=tuple(projects), services=(), discord=discord or DiscordPolicy())


ELUM = make_project("elum", "이룸", error=("member", "dev"))
SAMPLE = make_project("sample", "샘플")
REGISTRY = make_registry(ELUM, SAMPLE)


def to_discord_text_channel_name(name: str) -> str:
    """디스코드가 텍스트 채널 이름을 저장하는 형태 흉내 (소문자, 공백 > '-')"""
    return re.sub(r"\s+", "-", name.strip().lower())


class FakeDiscordClient:
    """메모리 디스코드 서버: 생성·수정 반영(텍스트 채널 이름 정규화), 변경 호출 기록, 이름 지정 실패 주입"""

    def __init__(self, failing_names: tuple[str, ...] = (), is_onboarding_accepted: bool = True):
        self.channels: list[dict] = []
        self.roles: list[dict] = [{"id": GUILD_ID, "name": "@everyone"}]
        self.calls: list[tuple] = []
        self.onboarding_payloads: list[dict] = []
        self.failing_names = set(failing_names)
        self.is_onboarding_accepted = is_onboarding_accepted
        self.is_listing_broken = False
        self._next_id = 100

    def _new_id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def _fail_if_requested(self, name: str) -> None:
        if name in self.failing_names:
            raise DiscordError(403, "Missing Permissions")

    def list_channels(self) -> list[dict]:
        if self.is_listing_broken:
            raise DiscordError(401, "401: Unauthorized")
        return copy.deepcopy(self.channels)

    def list_roles(self) -> list[dict]:
        return copy.deepcopy(self.roles)

    def create_role(self, name: str) -> dict:
        self.calls.append(("create_role", name))
        self._fail_if_requested(name)
        role = {"id": self._new_id(), "name": name}
        self.roles.append(role)
        return copy.deepcopy(role)

    def create_channel(self, name: str, channel_type: int, parent_id: str | None, overwrites: list[dict]) -> dict:
        self.calls.append(("create_channel", name, channel_type, parent_id))
        self._fail_if_requested(name)
        stored_name = to_discord_text_channel_name(name) if channel_type == 0 else name
        channel = {"id": self._new_id(), "name": stored_name, "type": channel_type, "parent_id": parent_id,
                   "permission_overwrites": copy.deepcopy(overwrites)}
        self.channels.append(channel)
        return copy.deepcopy(channel)

    def edit_channel(self, channel_id: str, **fields) -> dict:
        self.calls.append(("edit_channel", channel_id, copy.deepcopy(fields)))
        channel = self.channel_by_id(channel_id)
        self._fail_if_requested(channel["name"])
        channel.update(copy.deepcopy(fields))
        if channel["type"] == 0:
            channel["name"] = to_discord_text_channel_name(channel["name"])
        return copy.deepcopy(channel)

    def put_onboarding(self, payload: dict) -> bool:
        self.onboarding_payloads.append(copy.deepcopy(payload))
        return self.is_onboarding_accepted

    # ---- 테스트 조회 도우미 ----

    def mutation_calls(self) -> list[tuple]:
        return [call for call in self.calls if call[0] in ("create_role", "create_channel", "edit_channel")]

    def channel_by_id(self, channel_id: str) -> dict:
        return next(channel for channel in self.channels if channel["id"] == channel_id)

    def role_id(self, name: str) -> str:
        return next(role["id"] for role in self.roles if role["name"] == name)

    def category(self, name: str) -> dict:
        return next(channel for channel in self.channels if channel["type"] == 4 and channel["name"] == name)

    def channel(self, name: str, parent_name: str | None = None) -> dict:
        parent_id = self.category(parent_name)["id"] if parent_name else None
        return next(channel for channel in self.channels
                    if channel["type"] != 4 and channel["name"] == name and channel.get("parent_id") == parent_id)

    def add_channel(self, name: str, channel_type: int, parent_id: str | None = None,
                    overwrites: list[dict] | None = None) -> dict:
        channel = {"id": self._new_id(), "name": name, "type": channel_type, "parent_id": parent_id,
                   "permission_overwrites": overwrites or []}
        self.channels.append(channel)
        return channel

    def remove_channel(self, channel_id: str) -> None:
        self.channels = [channel for channel in self.channels if channel["id"] != channel_id]

    def remove_role(self, name: str) -> None:
        self.roles = [role for role in self.roles if role["name"] != name]

    def add_role(self, name: str) -> dict:
        role = {"id": self._new_id(), "name": name}
        self.roles.append(role)
        return role


def overwrite_map(channel: dict) -> dict[str, tuple[int, int, int]]:
    """덮어쓰기 id > (type, allow, deny) 정수 비교용"""
    return {str(overwrite["id"]): (int(overwrite["type"]), int(overwrite["allow"]), int(overwrite["deny"]))
            for overwrite in channel["permission_overwrites"]}
