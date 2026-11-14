"""앱 확인할 일 디스코드 채널: 소스 있는 프로젝트만 생성, 공개 대상 dev+관리자, 소스 삭제 후 보존, 기존 4종 불변, 알림 경로"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from control_tower_discord_fakes import (
    ELUM, GUILD_ID, REGISTRY, SAMPLE, VIEW_CHANNEL, FakeDiscordClient, make_registry, overwrite_map,
)

from service.control_tower.alert_planner import Notification
from service.control_tower.app_attention_store import AttentionSource
from service.control_tower.discord_sync import plan_sync, sync_discord
from service.control_tower.event_dispatcher import EventDispatcher
from service.control_tower.registry_models import PROJECT_CHANNEL_KINDS
from service.control_tower.store import ControlTowerStore

ATTENTION_CHANNEL_NAME = "확인할일"
BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def _add_source(store: ControlTowerStore, project_id: str, source_id: str = "api") -> None:
    store.save_attention_source(AttentionSource(
        project_id, source_id, "https://example.com/attention", True, "both", 60, 5, 300, BASE_TIME, BASE_TIME))


def _created_attention_scopes(operations) -> list[str]:
    return [operation.scope for operation in operations
            if operation.action == "create_channel" and operation.kind == "attention"]


def test_소스가_있는_프로젝트만_확인할일_채널_생성을_계획한다(store):
    _add_source(store, "elum")
    client = FakeDiscordClient()

    operations = plan_sync(REGISTRY, client.list_channels(), client.list_roles(), GUILD_ID, store.all_bindings(),
                           frozenset({"elum"}))

    assert _created_attention_scopes(operations) == ["elum"]
    created = next(operation for operation in operations if operation.kind == "attention")
    assert (created.name, created.parent_scope) == (ATTENTION_CHANNEL_NAME, "elum")


def test_소스_집합을_주지_않으면_기존_계획과_같아_확인할일_채널이_없다(store):
    client = FakeDiscordClient()
    operations = plan_sync(REGISTRY, client.list_channels(), client.list_roles(), GUILD_ID, store.all_bindings())

    assert _created_attention_scopes(operations) == []
    assert len([operation for operation in operations if operation.action == "create_channel"]) == 3 + 4 * 2


def test_동기화하면_소스_있는_프로젝트에만_채널이_생기고_dev와_관리자만_볼_수_있다(store):
    _add_source(store, "elum")
    client = FakeDiscordClient()

    report = sync_discord(REGISTRY, client, store, GUILD_ID)

    assert report.errors == []
    channel = client.channel(ATTENTION_CHANNEL_NAME, "이룸")
    assert overwrite_map(channel) == {
        GUILD_ID: (0, 0, VIEW_CHANNEL), client.role_id("elum-dev"): (0, VIEW_CHANNEL, 0),
        client.role_id("관리자"): (0, VIEW_CHANNEL, 0)}
    assert store.get_binding("elum", "attention") == channel["id"]
    assert not any(c["name"] == ATTENTION_CHANNEL_NAME and c["parent_id"] == client.category("샘플")["id"]
                   for c in client.channels)
    assert store.get_binding("sample", "attention") is None
    # 두 번째 동기화는 변경 없음
    calls_before = len(client.mutation_calls())
    sync_discord(REGISTRY, client, store, GUILD_ID)
    assert len(client.mutation_calls()) == calls_before


def test_소스를_모두_지워도_기존_확인할일_채널은_보관하거나_바꾸지_않는다(store):
    _add_source(store, "elum")
    client = FakeDiscordClient()
    sync_discord(REGISTRY, client, store, GUILD_ID)
    channel_before = dict(client.channel(ATTENTION_CHANNEL_NAME, "이룸"))
    store.delete_attention_source("elum", "api")

    operations = plan_sync(REGISTRY, client.list_channels(), client.list_roles(), GUILD_ID, store.all_bindings(),
                           frozenset())
    report = sync_discord(REGISTRY, client, store, GUILD_ID)

    assert operations == []
    assert (report.created, report.updated, report.archived) == (0, 0, 0)
    assert client.channel(ATTENTION_CHANNEL_NAME, "이룸") == channel_before
    assert store.get_binding("elum", "attention") == channel_before["id"]


def test_channels에_attention이_없는_프로젝트는_소스가_있어도_채널이_없다(store):
    limited = replace(ELUM, channel_kinds=("status", "error"))
    _add_source(store, "elum")
    client = FakeDiscordClient()
    operations = plan_sync(make_registry(limited, SAMPLE), client.list_channels(), client.list_roles(), GUILD_ID,
                           store.all_bindings(), frozenset({"elum"}))

    assert _created_attention_scopes(operations) == []


def test_숨김_프로젝트도_다른_채널_종류와_같은_규칙으로_계획한다(store):
    hidden = replace(ELUM, is_hidden=True)
    client = FakeDiscordClient()
    with_source = plan_sync(make_registry(hidden), client.list_channels(), client.list_roles(), GUILD_ID,
                            store.all_bindings(), frozenset({"elum"}))
    without_source = plan_sync(make_registry(hidden), client.list_channels(), client.list_roles(), GUILD_ID,
                               store.all_bindings(), frozenset())

    assert _created_attention_scopes(with_source) == ["elum"]
    assert _created_attention_scopes(without_source) == []


def test_소스가_없는_프로젝트의_기존_4종_채널_계획은_변화가_없다(store):
    client = FakeDiscordClient()
    plan_with_empty_set = plan_sync(REGISTRY, client.list_channels(), client.list_roles(), GUILD_ID,
                                    store.all_bindings(), frozenset())
    plan_without_argument = plan_sync(REGISTRY, client.list_channels(), client.list_roles(), GUILD_ID,
                                      store.all_bindings())

    assert plan_with_empty_set == plan_without_argument
    assert {operation.kind for operation in plan_with_empty_set if operation.action == "create_channel"} == {
        "status", "error", "report", "deploy", "notice", "alert", "digest"}


def test_채널_종류_기본값에_attention이_들어_있다():
    assert "attention" in PROJECT_CHANNEL_KINDS


# ---- 알림 경로 ----

class _FakeBindingStore:
    def __init__(self, bindings: dict[tuple[str, str], str]):
        self.bindings = bindings

    def get_binding(self, scope: str, kind: str) -> str | None:
        return self.bindings.get((scope, kind))


class _FakeDiscordSender:
    def __init__(self):
        self.sent: list[str] = []

    def send_embed(self, channel_id: str, embed: dict) -> bool:
        self.sent.append(channel_id)
        return True


def _dispatch_attention(bindings: dict[tuple[str, str], str]) -> list[str]:
    sender = _FakeDiscordSender()
    registry = make_registry(ELUM)
    dispatcher = EventDispatcher(_FakeBindingStore(bindings), lambda: sender, "https://status.example.com")
    dispatcher.dispatch(Notification(scope="elum", kind="attention", severity="warning", title="elum 확인할 일",
                                     body="새 의견 +2", service_ids=(), dedupe_key=""))
    return sender.sent


def test_디스패처는_attention_종류_바인딩으로_채널을_찾는다():
    assert _dispatch_attention({("elum", "attention"): "c-attention", ("global", "alert"): "c-alert"}) == ["c-attention"]


def test_attention_채널_바인딩이_없으면_관제_긴급으로_대체한다():
    assert _dispatch_attention({("global", "alert"): "c-alert"}) == ["c-alert"]
