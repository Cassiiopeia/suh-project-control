"""관제소 디스코드 동기화 + 사용자 정의 알림 종류: 채널 생성, 관리자만 공개, 기본 채널 이름 충돌, 제거 시 보관, 재등록 시 복원"""
from __future__ import annotations

from dataclasses import replace

import pytest
from control_tower_discord_fakes import ELUM, GUILD_ID, VIEW_CHANNEL, FakeDiscordClient, make_registry, overwrite_map

from service.control_tower.discord_sync import plan_sync, sync_discord
from service.control_tower.discord_sync_models import (
    ACTION_ARCHIVE_CHANNEL, ACTION_BIND, ACTION_CREATE_CHANNEL, ACTION_UPDATE_CHANNEL,
)
from service.control_tower.registry_models import EventKindSpec
from service.control_tower.store import ControlTowerStore

ADMIN_ROLE_NAME = "관리자"
BASE_REGISTRY = make_registry(ELUM)
CLAUDE_CODE_KIND = EventKindSpec("claude-code", "클로드코드", ("dev",))


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def _registry_with_event_kinds(*event_kinds: EventKindSpec):
    return make_registry(replace(ELUM, event_kinds=event_kinds))


def _plan(client: FakeDiscordClient, store: ControlTowerStore, registry):
    return plan_sync(registry, client.list_channels(), client.list_roles(), GUILD_ID, store.all_bindings())


def _synced_client(store: ControlTowerStore, registry=BASE_REGISTRY) -> FakeDiscordClient:
    client = FakeDiscordClient()
    assert sync_discord(registry, client, store, GUILD_ID).errors == []
    return client


def _operations_for_kind(operations, kind: str):
    return [operation for operation in operations if (operation.scope, operation.kind) == ("elum", kind)]


def test_plan_admin_only_custom_kind(store):
    client = _synced_client(store)
    admin_only_registry = _registry_with_event_kinds(EventKindSpec("ops-log", "운영로그", ()))

    [operation] = _operations_for_kind(_plan(client, store, admin_only_registry), "ops-log")
    assert operation.action == ACTION_CREATE_CHANNEL
    assert operation.overwrites == (
        {"id": GUILD_ID, "type": 0, "allow": 0, "deny": VIEW_CHANNEL},
        {"ref": "global:admin", "type": 0, "allow": VIEW_CHANNEL, "deny": 0},
    )

    assert sync_discord(admin_only_registry, client, store, GUILD_ID).errors == []
    channel = client.channel_by_id(store.get_binding("elum", "ops-log"))
    assert overwrite_map(channel) == {GUILD_ID: (0, 0, VIEW_CHANNEL),
                                      client.role_id(ADMIN_ROLE_NAME): (0, VIEW_CHANNEL, 0)}
    assert _plan(client, store, admin_only_registry) == []


def test_plan_creates_custom_event_kind_channel(store):
    client = _synced_client(store)
    registry = _registry_with_event_kinds(CLAUDE_CODE_KIND)

    [operation] = _operations_for_kind(_plan(client, store, registry), "claude-code")
    assert (operation.action, operation.name, operation.parent_scope) == (ACTION_CREATE_CHANNEL, "클로드코드", "elum")
    # 기존 error 채널(dev 공개)과 같은 모양: everyone 차단 + elum-dev + 관리자
    assert operation.overwrites == (
        {"id": GUILD_ID, "type": 0, "allow": 0, "deny": VIEW_CHANNEL},
        {"ref": "elum:dev", "type": 0, "allow": VIEW_CHANNEL, "deny": 0},
        {"ref": "global:admin", "type": 0, "allow": VIEW_CHANNEL, "deny": 0},
    )

    assert sync_discord(registry, client, store, GUILD_ID).errors == []
    channel = client.channel_by_id(store.get_binding("elum", "claude-code"))
    assert channel["parent_id"] == store.get_binding("elum", "_category")
    assert overwrite_map(channel) == {GUILD_ID: (0, 0, VIEW_CHANNEL),
                                      client.role_id("elum-dev"): (0, VIEW_CHANNEL, 0),
                                      client.role_id(ADMIN_ROLE_NAME): (0, VIEW_CHANNEL, 0)}
    assert _plan(client, store, registry) == []


def test_plan_custom_kind_does_not_take_default_channel_by_name(store):
    client = _synced_client(store)
    report_channel_id = store.get_binding("elum", "report")
    assert client.channel_by_id(report_channel_id)["name"] == "신고"
    registry = _registry_with_event_kinds(EventKindSpec("user-report", "신고", ("dev",)))

    operations = _plan(client, store, registry)

    [operation] = _operations_for_kind(operations, "user-report")
    assert operation.action == ACTION_CREATE_CHANNEL
    assert all(operation.target_id != report_channel_id for operation in operations)
    assert not [operation for operation in operations if operation.action == ACTION_BIND]


def test_plan_archives_removed_custom_kind_channel(store):
    client = _synced_client(store, _registry_with_event_kinds(EventKindSpec("old-kind", "옛종류", ("dev",))))
    old_channel_id = store.get_binding("elum", "old-kind")

    operations = _plan(client, store, BASE_REGISTRY)

    # 사용자 정의 종류 채널 1개만 보관 (기본 채널·카테고리·역할 바인딩은 대상 아님)
    [operation] = operations
    assert (operation.action, operation.scope, operation.kind, operation.target_id) == (
        ACTION_ARCHIVE_CHANNEL, "elum", "old-kind", old_channel_id)
    assert operation.name == "옛종류"  # 텍스트 채널 이름은 그대로 (빠진 프로젝트 하위 채널과 같은 방식)
    assert operation.overwrites == (
        {"id": GUILD_ID, "type": 0, "allow": 0, "deny": VIEW_CHANNEL},
        {"ref": "global:admin", "type": 0, "allow": VIEW_CHANNEL, "deny": 0},
    )

    report = sync_discord(BASE_REGISTRY, client, store, GUILD_ID)
    assert (report.archived, report.errors) == (1, [])
    assert client.channel_by_id(old_channel_id)["name"] == "옛종류"
    assert overwrite_map(client.channel_by_id(old_channel_id)) == {
        GUILD_ID: (0, 0, VIEW_CHANNEL), client.role_id(ADMIN_ROLE_NAME): (0, VIEW_CHANNEL, 0)}
    assert _plan(client, store, BASE_REGISTRY) == []  # 관리자만 권한이면 재계획 없음 (이름 정규화와 무관)


def test_plan_reuses_bound_channel_when_kind_readded(store):
    registry = _registry_with_event_kinds(CLAUDE_CODE_KIND)
    client = _synced_client(store, registry)
    channel_id = store.get_binding("elum", "claude-code")
    overwrites_before = overwrite_map(client.channel_by_id(channel_id))
    assert sync_discord(BASE_REGISTRY, client, store, GUILD_ID).errors == []
    assert client.role_id("elum-dev") not in overwrite_map(client.channel_by_id(channel_id))
    client.channel_by_id(channel_id)["name"] = "옛-이름"  # 보관 중 관리자가 바꾼 이름도 복원 대상

    [operation] = _plan(client, store, registry)

    assert (operation.action, operation.kind, operation.target_id, operation.name) == (
        ACTION_UPDATE_CHANNEL, "claude-code", channel_id, "클로드코드")
    assert sync_discord(registry, client, store, GUILD_ID).errors == []
    assert client.channel_by_id(channel_id)["name"] == "클로드코드"
    assert overwrite_map(client.channel_by_id(channel_id)) == overwrites_before
    assert _plan(client, store, registry) == []


def test_plan_does_not_archive_removed_kind_channel_taken_by_new_kind_with_same_name(store):
    client = _synced_client(store, _registry_with_event_kinds(EventKindSpec("old-kind", "공용채널", ("dev",))))
    shared_channel_id = store.get_binding("elum", "old-kind")
    renamed_registry = _registry_with_event_kinds(EventKindSpec("new-kind", "공용채널", ("dev",)))

    [operation] = _plan(client, store, renamed_registry)

    # 같은 채널에 바인딩과 보관이 함께 계획되지 않음
    assert (operation.action, operation.kind, operation.target_id) == (ACTION_BIND, "new-kind", shared_channel_id)
