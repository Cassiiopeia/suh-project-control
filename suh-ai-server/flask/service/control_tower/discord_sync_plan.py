"""디스코드 구조 동기화 계획 (순수): 등록 파일 <-> 현재 역할·카테고리·채널 비교 > 작업 목록
삭제 없음, 등록에서 빠진 프로젝트 카테고리는 보관(이름 접두사 + 관리자만), 빠진 사용자 정의 종류 채널은 관리자만, 보기 권한 비트만 관리
"""
from __future__ import annotations

import re

from service.control_tower.discord_sync_models import (
    ACTION_ARCHIVE_CATEGORY, ACTION_ARCHIVE_CHANNEL, ACTION_BIND, ACTION_CREATE_CATEGORY, ACTION_CREATE_CHANNEL,
    ACTION_CREATE_ROLE, ACTION_UPDATE_CHANNEL, ADMIN_ROLE_KEY, ADMIN_ROLE_REFERENCE, ARCHIVE_NAME_PREFIX,
    CATEGORY_CHANNEL_TYPE, CATEGORY_KIND, EVERYONE_ROLE_KEY, GLOBAL_SCOPE, PROJECT_NAME_PLACEHOLDER, ROLE_KIND_PREFIX,
    ROLE_OVERWRITE_TYPE, VIEW_CHANNEL_PERMISSION, SyncOperation, role_reference,
)
from service.control_tower.discord_sync_event_kinds import RemovedEventKindFinder
from service.control_tower.registry import ProjectSpec, Registry
from service.control_tower.registry_models import ATTENTION_CHANNEL_KIND


def plan_sync(registry: Registry, current_channels: list[dict], current_roles: list[dict], guild_id: str,
              bindings: dict[tuple[str, str], str],
              attention_project_ids: frozenset[str] = frozenset()) -> list[SyncOperation]:
    """동기화 계획: 역할 > 카테고리 > 전역 채널 > 프로젝트 채널 > 사용자 정의 종류 채널 > 보관 (변경 없으면 빈 목록)
    attention_project_ids: 앱 확인할 일 소스가 있는 프로젝트 (이 프로젝트만 attention 채널 계획)"""
    planner = _SyncPlanner(registry, current_channels, current_roles, guild_id, bindings, attention_project_ids)
    return planner.plan()


class _SyncPlanner:
    def __init__(self, registry: Registry, current_channels: list[dict], current_roles: list[dict], guild_id: str,
                 bindings: dict[tuple[str, str], str], attention_project_ids: frozenset[str]):
        self._registry = registry
        self._attention_project_ids = attention_project_ids
        self._policy = registry.discord
        self._channels = current_channels
        self._channel_by_id = {str(channel["id"]): channel for channel in current_channels}
        self._roles = current_roles
        self._role_ids = {str(role["id"]) for role in current_roles}
        self._guild_id = str(guild_id)
        self._bindings = bindings
        # 계획 중 확정된 id: 역할 참조 > id, 프로젝트 id > 카테고리 id
        self._role_id_by_reference: dict[str, str] = {}
        self._category_id_by_project: dict[str, str] = {}
        self._managed_overwrite_ids: set[str] = set()
        self._removed_event_kinds = RemovedEventKindFinder(registry)
        # 등록된 프로젝트·전역 키가 이미 쓰는 채널 id (다른 키의 이름 매칭·보관 대상에서 제외)
        self._claimed_channel_ids = self._collect_live_bound_channel_ids()
        self._operations: list[SyncOperation] = []

    def plan(self) -> list[SyncOperation]:
        self._plan_roles()
        self._managed_overwrite_ids = self._collect_managed_overwrite_ids()
        for project in self._registry.projects:
            self._plan_category(project)
        for kind, visible_role_keys in self._policy.global_channels.items():
            self._plan_channel(GLOBAL_SCOPE, kind, visible_role_keys, parent_scope=None)
        for project in self._registry.projects:
            for kind in self._planned_channel_kinds(project):
                visible_role_keys = project.channel_visibility.get(kind, self._policy.channel_visibility.get(kind, ()))
                self._plan_channel(project.id, kind, visible_role_keys, parent_scope=project.id)
        # 사용자 정의 종류: 기본 채널이 먼저 바인딩을 잡은 뒤 계획 (같은 이름 기본 채널을 가져가지 않음)
        for project in self._registry.projects:
            for event_kind in project.event_kinds:
                self._plan_channel(project.id, event_kind.kind, event_kind.visible_to, parent_scope=project.id,
                                   name=event_kind.channel_name)
        self._plan_archives()
        self._plan_removed_event_kind_archives()
        return self._operations

    def _planned_channel_kinds(self, project: ProjectSpec) -> tuple[str, ...]:
        """프로젝트 채널 종류 중 이번에 계획할 것 (attention은 소스 있는 프로젝트만, 없어진 뒤 기존 채널은 건드리지 않음)"""
        return tuple(kind for kind in project.channel_kinds
                     if kind != ATTENTION_CHANNEL_KIND or project.id in self._attention_project_ids)

    # ---- 역할 ----

    def _plan_roles(self) -> None:
        """역할 매칭 (바인딩 id > 같은 이름), 없으면 생성"""
        for scope, role_key, name in self._role_specs():
            kind = ROLE_KIND_PREFIX + role_key
            bound_id = self._bindings.get((scope, kind))
            if bound_id in self._role_ids:
                self._role_id_by_reference[role_reference(scope, role_key)] = bound_id
                continue
            named_role = next((role for role in self._roles if role.get("name") == name), None)
            if named_role is None:
                self._operations.append(SyncOperation(ACTION_CREATE_ROLE, scope, kind, name))
                continue
            role_id = str(named_role["id"])
            self._role_id_by_reference[role_reference(scope, role_key)] = role_id
            self._operations.append(SyncOperation(ACTION_BIND, scope, kind, name, target_id=role_id))

    def _role_specs(self) -> list[tuple[str, str, str]]:
        """(scope, 역할 키, 이름): 프로젝트마다 role_names 전부 + 전역 관리자"""
        specs = [
            (project.id, role_key, template.replace(PROJECT_NAME_PLACEHOLDER, project.id))
            for project in self._registry.projects
            for role_key, template in self._policy.role_names.items()
        ]
        specs.append((GLOBAL_SCOPE, ADMIN_ROLE_KEY, self._policy.admin_role_name))
        return specs

    def _collect_managed_overwrite_ids(self) -> set[str]:
        """관리 대상 덮어쓰기 id: @everyone + 확정 역할 + 바인딩된 역할 (보관 프로젝트 역할 포함)"""
        bound_role_ids = {discord_id for (_, kind), discord_id in self._bindings.items()
                          if kind.startswith(ROLE_KIND_PREFIX)}
        return {self._guild_id} | set(self._role_id_by_reference.values()) | bound_role_ids

    def _collect_live_bound_channel_ids(self) -> set[str]:
        """등록된 프로젝트·전역 scope에 바인딩된 카테고리·채널 id (보관 대상 프로젝트·제거된 사용자 정의 종류 제외)"""
        live_scopes = {project.id for project in self._registry.projects} | {GLOBAL_SCOPE}
        return {discord_id for (scope, kind), discord_id in self._bindings.items()
                if scope in live_scopes and not kind.startswith(ROLE_KIND_PREFIX)
                and not self._removed_event_kinds.is_removed_event_kind(scope, kind)}

    # ---- 카테고리·채널 ----

    def _plan_category(self, project: ProjectSpec) -> None:
        """프로젝트 카테고리: @everyone 차단 + 프로젝트 역할 전부·관리자 허용 (새 채널이 상속)"""
        visible_role_keys = tuple(self._policy.role_names)
        candidates = [channel for channel in self._channels if channel.get("type") == CATEGORY_CHANNEL_TYPE]
        category = self._find_existing(project.id, CATEGORY_KIND, project.name, candidates)
        if category is None:
            self._operations.append(SyncOperation(
                ACTION_CREATE_CATEGORY, project.id, CATEGORY_KIND, project.name,
                overwrites=self._managed_overwrites(None, project.id, visible_role_keys)))
            return
        self._category_id_by_project[project.id] = str(category["id"])
        self._plan_update(ACTION_UPDATE_CHANNEL, project.id, CATEGORY_KIND, project.name, category,
                          self._managed_overwrites(category, project.id, visible_role_keys))

    def _plan_channel(self, scope: str, kind: str, visible_role_keys: tuple[str, ...], parent_scope: str | None,
                      name: str | None = None) -> None:
        """채널 매칭 (바인딩 id > 같은 부모 안 같은 이름), 없으면 생성, 다르면 수정 (name 생략 시 channel_names 조회)"""
        name = _text_channel_name(name if name is not None else self._policy.channel_names.get(kind, kind))
        parent_id = self._category_id_by_project.get(parent_scope) if parent_scope else None
        is_parent_pending = parent_scope is not None and parent_id is None
        candidates = [] if is_parent_pending else [
            channel for channel in self._channels
            if channel.get("type") != CATEGORY_CHANNEL_TYPE and _parent_id_of(channel) == parent_id
        ]
        channel = self._find_existing(scope, kind, name, candidates)
        if channel is None:
            self._operations.append(SyncOperation(
                ACTION_CREATE_CHANNEL, scope, kind, name,
                overwrites=self._managed_overwrites(None, scope, visible_role_keys), parent_scope=parent_scope))
            return
        self._plan_update(ACTION_UPDATE_CHANNEL, scope, kind, name, channel,
                          self._managed_overwrites(channel, scope, visible_role_keys))

    def _find_existing(self, scope: str, kind: str, name: str, name_candidates: list[dict]) -> dict | None:
        """바인딩 id가 아직 있으면 그것, 없으면 다른 키가 안 쓰는 같은 이름 (이름 매칭 시 바인딩 작업 추가)"""
        bound_id = self._bindings.get((scope, kind))
        if bound_id in self._channel_by_id:
            self._claimed_channel_ids.add(bound_id)
            return self._channel_by_id[bound_id]
        named_channel = next((channel for channel in name_candidates
                              if str(channel["id"]) not in self._claimed_channel_ids and _is_same_name(channel, name)),
                             None)
        if named_channel is not None:
            self._claimed_channel_ids.add(str(named_channel["id"]))
            self._operations.append(SyncOperation(ACTION_BIND, scope, kind, name, target_id=str(named_channel["id"])))
        return named_channel

    # ---- 보관 ----

    def _plan_archives(self) -> None:
        """등록에서 빠진 프로젝트 카테고리 + 하위 채널 > 보관 이름, 관리자만 (등록 프로젝트가 쓰는 카테고리·채널 제외)"""
        project_ids = {project.id for project in self._registry.projects}
        for (scope, kind), category_id in sorted(self._bindings.items()):
            if kind != CATEGORY_KIND or scope in project_ids or scope == GLOBAL_SCOPE:
                continue
            if category_id in self._claimed_channel_ids:
                continue
            category = self._channel_by_id.get(category_id)
            if category is None:
                continue
            self._plan_update(ACTION_ARCHIVE_CATEGORY, scope, CATEGORY_KIND, _archived_name(category["name"]),
                              category, self._managed_overwrites(category, scope, ()))
            for channel in self._channels:
                if _parent_id_of(channel) != category_id or str(channel["id"]) in self._claimed_channel_ids:
                    continue
                self._plan_update(ACTION_ARCHIVE_CHANNEL, scope, self._bound_kind(scope, str(channel["id"])),
                                  str(channel.get("name", "")), channel, self._managed_overwrites(channel, scope, ()))

    def _plan_removed_event_kind_archives(self) -> None:
        """등록 프로젝트에서 빠진 사용자 정의 종류 채널 > 관리자만 (이름 유지, 다른 키가 이름으로 가져간 채널 제외)"""
        for scope, kind, channel in self._removed_event_kinds.find_archivable_channels(
                self._bindings, self._channel_by_id, self._claimed_channel_ids):
            self._plan_update(ACTION_ARCHIVE_CHANNEL, scope, kind, str(channel.get("name", "")), channel,
                              self._managed_overwrites(channel, scope, ()))

    def _bound_kind(self, scope: str, channel_id: str) -> str | None:
        return next((kind for (bound_scope, kind), discord_id in self._bindings.items()
                     if bound_scope == scope and discord_id == channel_id), None)

    # ---- 권한 덮어쓰기 ----

    def _managed_overwrites(self, channel: dict | None, scope: str,
                            visible_role_keys: tuple[str, ...]) -> tuple[dict, ...]:
        """관리 덮어쓰기: 보기 비트만 공개 대상대로, 기존 다른 권한 비트 유지, 빠진 관리 역할은 보기 비트 제거"""
        current_by_id = {str(overwrite["id"]): overwrite for overwrite in self._current_managed(channel)}
        desired_targets: list[tuple[dict, bool]] = []  # (대상, 보기 허용 여부)
        if EVERYONE_ROLE_KEY not in visible_role_keys:
            desired_targets.append(({"id": self._guild_id}, False))
        for reference in self._visible_role_references(scope, visible_role_keys):
            desired_targets.append(({"ref": reference}, True))

        overwrites: list[dict] = []
        used_ids: set[str] = set()
        for target, is_view_allowed in desired_targets:
            target_id = target.get("id") or self._role_id_by_reference.get(target.get("ref"))
            other_allow, other_deny = _other_permission_bits(current_by_id.get(target_id))
            overwrites.append({**target, "type": ROLE_OVERWRITE_TYPE,
                               "allow": other_allow | (VIEW_CHANNEL_PERMISSION if is_view_allowed else 0),
                               "deny": other_deny | (0 if is_view_allowed else VIEW_CHANNEL_PERMISSION)})
            if target_id:
                used_ids.add(target_id)
        # 공개 대상에서 빠진 관리 역할: 보기 비트만 제거, 남는 권한 없으면 덮어쓰기 삭제
        for overwrite_id, current in current_by_id.items():
            other_allow, other_deny = _other_permission_bits(current)
            if overwrite_id not in used_ids and (other_allow or other_deny):
                overwrites.append({"id": overwrite_id, "type": ROLE_OVERWRITE_TYPE,
                                   "allow": other_allow, "deny": other_deny})
        return tuple(overwrites)

    def _visible_role_references(self, scope: str, visible_role_keys: tuple[str, ...]) -> list[str]:
        """공개 대상 역할 키 > 역할 참조 (전역 채널의 프로젝트 역할 키는 모든 프로젝트), 관리자 항상 포함"""
        references: list[str] = []
        for role_key in visible_role_keys:
            if role_key in (ADMIN_ROLE_KEY, EVERYONE_ROLE_KEY):
                continue
            scopes = [project.id for project in self._registry.projects] if scope == GLOBAL_SCOPE else [scope]
            references += [role_reference(role_scope, role_key) for role_scope in scopes]
        references.append(ADMIN_ROLE_REFERENCE)
        return list(dict.fromkeys(references))

    def _current_managed(self, channel: dict | None) -> list[dict]:
        if channel is None:
            return []
        return [overwrite for overwrite in channel.get("permission_overwrites") or [] if self._is_managed(overwrite)]

    def _is_managed(self, overwrite: dict) -> bool:
        return int(overwrite.get("type", 0)) == ROLE_OVERWRITE_TYPE and str(overwrite["id"]) in self._managed_overwrite_ids

    def _plan_update(self, action: str, scope: str, kind: str | None, name: str, channel: dict,
                     desired_overwrites: tuple[dict, ...]) -> None:
        """이름 또는 관리 덮어쓰기가 다를 때만 수정 작업 (개인·비관리 역할 덮어쓰기는 보존 목록으로)"""
        if _is_same_name(channel, name) and self._is_overwrites_equal(channel, desired_overwrites):
            return
        preserved = tuple(overwrite for overwrite in channel.get("permission_overwrites") or []
                          if not self._is_managed(overwrite))
        self._operations.append(SyncOperation(action, scope, kind, name, target_id=str(channel["id"]),
                                              overwrites=desired_overwrites, preserved_overwrites=preserved))

    def _is_overwrites_equal(self, channel: dict, desired_overwrites: tuple[dict, ...]) -> bool:
        """관리 덮어쓰기 비교 (allow·deny 정수 비교, 아직 없는 역할 참조가 있으면 다름)"""
        desired_set = set()
        for overwrite in desired_overwrites:
            overwrite_id = overwrite.get("id") or self._role_id_by_reference.get(overwrite.get("ref"))
            if overwrite_id is None:
                return False
            desired_set.add((overwrite_id, overwrite["type"], overwrite["allow"], overwrite["deny"]))
        current_set = {
            (str(overwrite["id"]), int(overwrite.get("type", 0)), int(overwrite.get("allow", 0)),
             int(overwrite.get("deny", 0)))
            for overwrite in self._current_managed(channel)
        }
        return desired_set == current_set


def _parent_id_of(channel: dict) -> str | None:
    parent_id = channel.get("parent_id")
    return str(parent_id) if parent_id else None


def _text_channel_name(name: str) -> str:
    """디스코드 텍스트 채널 저장 형태: 소문자, 공백 > '-' ('Server Status' > 'server-status', 한글 그대로)"""
    return re.sub(r"\s+", "-", name.strip().lower())


def _is_same_name(channel: dict, name: str) -> bool:
    """이름 비교 (카테고리는 그대로, 텍스트 채널은 디스코드 저장 형태로)"""
    current_name = str(channel.get("name", ""))
    if channel.get("type") == CATEGORY_CHANNEL_TYPE:
        return current_name == name
    return _text_channel_name(current_name) == _text_channel_name(name)


def _archived_name(name: str) -> str:
    """보관 접두사 1회만: '샘플' > '[보관] 샘플'"""
    return name if name.startswith(ARCHIVE_NAME_PREFIX) else ARCHIVE_NAME_PREFIX + name


def _other_permission_bits(overwrite: dict | None) -> tuple[int, int]:
    """기존 덮어쓰기의 보기 외 권한 비트 (allow, deny)"""
    if overwrite is None:
        return 0, 0
    return (int(overwrite.get("allow", 0)) & ~VIEW_CHANNEL_PERMISSION,
            int(overwrite.get("deny", 0)) & ~VIEW_CHANNEL_PERMISSION)
