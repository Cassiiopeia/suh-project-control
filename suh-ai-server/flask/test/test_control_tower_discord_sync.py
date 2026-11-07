"""관제소 디스코드 동기화: 빈 서버 생성 계획, 멱등, 공개 대상 덮어쓰기, 이름 매칭, 이름 변경, 개인 권한 보존, 보관"""
from __future__ import annotations

from dataclasses import replace

import pytest
from control_tower_discord_fakes import (
    ELUM, GUILD_ID, REGISTRY, SEND_MESSAGES, VIEW_CHANNEL, FakeDiscordClient, make_registry, overwrite_map,
)

from service.control_tower.discord_sync import plan_sync, sync_discord
from service.control_tower.store import ControlTowerStore

ADMIN_ROLE_NAME = "관리자"


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def _plan(client: FakeDiscordClient, store: ControlTowerStore, registry=REGISTRY):
    return plan_sync(registry, client.list_channels(), client.list_roles(), GUILD_ID, store.all_bindings())


def test_빈_서버는_역할_카테고리_전역채널_프로젝트채널_생성을_계획한다(store):
    operations = _plan(FakeDiscordClient(), store)

    names_by_action: dict[str, list[str]] = {}
    for operation in operations:
        names_by_action.setdefault(operation.action, []).append(operation.name)
    assert sorted(names_by_action["create_role"]) == sorted(["elum", "elum-dev", "sample", "sample-dev", ADMIN_ROLE_NAME])
    assert names_by_action["create_category"] == ["이룸", "샘플"]
    assert len(names_by_action["create_channel"]) == 3 + 4 * 2
    global_channels = [operation for operation in operations
                       if operation.action == "create_channel" and operation.scope == "global"]
    assert [operation.name for operation in global_channels] == ["공지", "관제-긴급", "관제-요약"]
    assert all(operation.parent_scope is None for operation in global_channels)
    elum_status = next(operation for operation in operations
                       if operation.action == "create_channel" and (operation.scope, operation.kind) == ("elum", "status"))
    assert elum_status.parent_scope == "elum"
    assert set(names_by_action) == {"create_role", "create_category", "create_channel"}


def test_동기화_후_두번째_계획은_비어_있고_재실행해도_변경_호출이_없다(store):
    client = FakeDiscordClient()
    first_report = sync_discord(REGISTRY, client, store, GUILD_ID)
    assert first_report.errors == []
    assert first_report.created == 5 + 2 + 11

    assert _plan(client, store) == []
    calls_before = len(client.mutation_calls())
    second_report = sync_discord(REGISTRY, client, store, GUILD_ID)
    assert len(client.mutation_calls()) == calls_before
    assert (second_report.created, second_report.updated, second_report.archived) == (0, 0, 0)


def test_채널_덮어쓰기는_공개_대상_역할과_관리자만_허용하고_everyone을_막는다(store):
    client = FakeDiscordClient()
    sync_discord(REGISTRY, client, store, GUILD_ID)
    admin_id = client.role_id(ADMIN_ROLE_NAME)
    deny_everyone = {GUILD_ID: (0, 0, VIEW_CHANNEL)}

    # elum error 덮어쓰기: member 포함 / sample error: dev만
    assert overwrite_map(client.channel("에러", "이룸")) == {
        **deny_everyone, client.role_id("elum"): (0, VIEW_CHANNEL, 0),
        client.role_id("elum-dev"): (0, VIEW_CHANNEL, 0), admin_id: (0, VIEW_CHANNEL, 0)}
    assert overwrite_map(client.channel("에러", "샘플")) == {
        **deny_everyone, client.role_id("sample-dev"): (0, VIEW_CHANNEL, 0), admin_id: (0, VIEW_CHANNEL, 0)}
    # 카테고리: 프로젝트 역할 전부 + 관리자
    assert overwrite_map(client.category("샘플")) == {
        **deny_everyone, client.role_id("sample"): (0, VIEW_CHANNEL, 0),
        client.role_id("sample-dev"): (0, VIEW_CHANNEL, 0), admin_id: (0, VIEW_CHANNEL, 0)}
    # 공지: everyone 공개라 막지 않음 / 관제-긴급: 관리자만
    assert overwrite_map(client.channel("공지")) == {admin_id: (0, VIEW_CHANNEL, 0)}
    assert overwrite_map(client.channel("관제-긴급")) == {**deny_everyone, admin_id: (0, VIEW_CHANNEL, 0)}
    assert client.channel("상태", "이룸")["parent_id"] == client.category("이룸")["id"]
    assert store.get_binding("elum", "role:member") == client.role_id("elum")
    assert store.get_binding("global", "role:admin") == admin_id
    assert store.get_binding("elum", "_category") == client.category("이룸")["id"]
    assert store.get_binding("global", "notice") == client.channel("공지")["id"]


def test_바인딩이_없으면_같은_이름의_기존_역할과_같은_부모의_채널을_재사용한다(store):
    client = FakeDiscordClient()
    existing_role = client.add_role("elum")
    existing_category = client.add_channel("이룸", 4)
    client.add_channel("상태", 0, parent_id=None)  # 부모가 다른 같은 이름 채널은 매칭 안 함
    existing_status = client.add_channel("상태", 0, parent_id=existing_category["id"])

    report = sync_discord(make_registry(ELUM), client, store, GUILD_ID)

    assert report.errors == []
    assert [role["name"] for role in client.roles].count("elum") == 1
    assert store.get_binding("elum", "role:member") == existing_role["id"]
    assert store.get_binding("elum", "_category") == existing_category["id"]
    assert store.get_binding("elum", "status") == existing_status["id"]
    assert client.role_id("elum") in overwrite_map(client.channel_by_id(existing_status["id"]))
    assert _plan(client, store, make_registry(ELUM)) == []


def test_바인딩된_객체가_사라졌으면_새로_만들고_바인딩을_갱신한다(store):
    client = FakeDiscordClient()
    store.set_binding("elum", "role:member", "555")  # 디스코드에서 지워진 역할

    sync_discord(make_registry(ELUM), client, store, GUILD_ID)

    assert store.get_binding("elum", "role:member") == client.role_id("elum")


def test_채널_이름이_바뀌면_덮어쓰기는_그대로_두고_이름만_고친다(store):
    client = FakeDiscordClient()
    sync_discord(REGISTRY, client, store, GUILD_ID)
    status_channel_id = store.get_binding("elum", "status")
    overwrites_before = overwrite_map(client.channel_by_id(status_channel_id))
    renamed_policy = replace(REGISTRY.discord, channel_names={**REGISTRY.discord.channel_names, "status": "상태판"})

    report = sync_discord(replace(REGISTRY, discord=renamed_policy), client, store, GUILD_ID)

    assert report.updated == 2  # elum·sample 상태 채널
    assert client.channel_by_id(status_channel_id)["name"] == "상태판"
    assert overwrite_map(client.channel_by_id(status_channel_id)) == overwrites_before


def test_공개_대상이_줄면_역할_허용을_빼고_개인_비관리_역할_다른_권한_비트는_보존한다(store):
    client = FakeDiscordClient()
    sync_discord(REGISTRY, client, store, GUILD_ID)
    status_channel = client.channel_by_id(store.get_binding("elum", "status"))
    outside_role = client.add_role("외부-봇")
    status_channel["permission_overwrites"] += [
        {"id": "7777", "type": 1, "allow": str(VIEW_CHANNEL), "deny": "0"},  # 관리자가 준 개인 권한
        {"id": outside_role["id"], "type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
    ]
    for overwrite in status_channel["permission_overwrites"]:
        if overwrite["id"] == client.role_id("elum-dev"):
            overwrite["allow"] = str(VIEW_CHANNEL | SEND_MESSAGES)
    narrowed_elum = replace(ELUM, channel_visibility={**ELUM.channel_visibility, "status": ("dev",)})

    sync_discord(replace(REGISTRY, projects=(narrowed_elum, REGISTRY.projects[1])), client, store, GUILD_ID)

    overwrites = overwrite_map(client.channel_by_id(status_channel["id"]))
    assert client.role_id("elum") not in overwrites
    assert overwrites["7777"] == (1, VIEW_CHANNEL, 0)
    assert overwrites[outside_role["id"]] == (0, VIEW_CHANNEL, 0)
    assert overwrites[client.role_id("elum-dev")] == (0, VIEW_CHANNEL | SEND_MESSAGES, 0)
    assert overwrites[GUILD_ID] == (0, 0, VIEW_CHANNEL)


def test_everyone의_보기_외_권한_제한은_유지하고_변경으로_보지_않는다(store):
    client = FakeDiscordClient()
    sync_discord(REGISTRY, client, store, GUILD_ID)
    notice_channel = client.channel("공지")
    notice_channel["permission_overwrites"].append({"id": GUILD_ID, "type": 0, "allow": "0", "deny": str(SEND_MESSAGES)})

    assert _plan(client, store) == []


def test_등록에서_빠진_프로젝트_카테고리는_보관_이름과_관리자만_권한으로_바뀌고_삭제하지_않는다(store):
    client = FakeDiscordClient()
    sync_discord(REGISTRY, client, store, GUILD_ID)
    channel_count = len(client.channels)
    sample_category_id = store.get_binding("sample", "_category")
    admin_only = {GUILD_ID: (0, 0, VIEW_CHANNEL), client.role_id(ADMIN_ROLE_NAME): (0, VIEW_CHANNEL, 0)}
    only_elum = make_registry(ELUM)

    report = sync_discord(only_elum, client, store, GUILD_ID)

    assert report.errors == []
    assert report.archived == 1 + 4
    assert len(client.channels) == channel_count
    assert client.channel_by_id(sample_category_id)["name"] == "[보관] 샘플"
    assert overwrite_map(client.channel_by_id(sample_category_id)) == admin_only
    for channel in client.channels:
        if channel.get("parent_id") == sample_category_id:
            assert overwrite_map(channel) == admin_only
    assert _plan(client, store, only_elum) == []  # 접두사 중복 없음

    # 다시 등록하면 원래 이름·권한으로 복귀
    sync_discord(REGISTRY, client, store, GUILD_ID)
    assert client.channel_by_id(sample_category_id)["name"] == "샘플"
    assert client.role_id("sample") in overwrite_map(client.channel_by_id(sample_category_id))
