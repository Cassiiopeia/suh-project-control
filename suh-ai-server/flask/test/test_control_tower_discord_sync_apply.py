"""관제소 디스코드 동기화 실행: 실패 기록 후 계속, 의존 작업 건너뛰기, 온보딩 질문 구성·실패 흡수"""
from __future__ import annotations

import pytest
from control_tower_discord_fakes import GUILD_ID, REGISTRY, SAMPLE, FakeDiscordClient, make_project, make_registry

from service.control_tower.discord_sync import build_onboarding_payload, sync_discord
from service.control_tower.store import ControlTowerStore

BOT_TOKEN = "secret-bot-token"


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def test_역할_생성이_실패하면_오류를_남기고_그_역할에_기대는_작업만_건너뛴다(store):
    client = FakeDiscordClient(failing_names=("elum",))

    report = sync_discord(REGISTRY, client, store, GUILD_ID)

    assert any("create_role elum/role:member" in error and "403" in error for error in report.errors)
    assert all(BOT_TOKEN not in error for error in report.errors)
    # elum 카테고리·채널은 elum member 역할을 참조해 건너뜀, 나머지는 생성
    assert not any(call[0] == "create_channel" and call[1] == "이룸" for call in client.calls)
    assert store.get_binding("elum", "_category") is None
    assert store.get_binding("sample", "_category") is not None
    assert store.get_binding("global", "notice") is not None
    assert report.created == 4 + 1 + 3 + 4  # 역할 4, sample 카테고리, 전역 3, sample 채널 4


def test_카테고리_생성이_실패하면_그_아래_채널은_건너뛰고_다른_프로젝트는_계속한다(store):
    client = FakeDiscordClient(failing_names=("샘플",))

    report = sync_discord(REGISTRY, client, store, GUILD_ID)

    assert len([error for error in report.errors if error.startswith("create_category")]) == 1
    assert len([error for error in report.errors if "skipped" in error]) == 4
    assert store.get_binding("sample", "status") is None
    assert store.get_binding("elum", "status") is not None


def test_목록_조회가_실패하면_오류만_담아_반환한다(store):
    client = FakeDiscordClient()
    client.is_listing_broken = True

    report = sync_discord(REGISTRY, client, store, GUILD_ID)

    assert len(report.errors) == 1 and "401" in report.errors[0]
    assert client.calls == [] and client.onboarding_payloads == []
    assert report.is_onboarding_applied is False


def test_온보딩은_프로젝트별_member_역할_옵션과_공지_기본채널로_보낸다(store):
    client = FakeDiscordClient()

    report = sync_discord(REGISTRY, client, store, GUILD_ID)

    assert report.is_onboarding_applied is True
    payload = client.onboarding_payloads[-1]
    prompt = payload["prompts"][0]
    assert prompt["single_select"] is False and prompt["required"] is False
    assert [option["role_ids"] for option in prompt["options"]] == [[client.role_id("elum")], [client.role_id("sample")]]
    assert payload["default_channel_ids"] == [client.channel("공지")["id"]]


def test_온보딩_실패는_동기화를_멈추지_않고_적용_여부만_False다(store):
    client = FakeDiscordClient(is_onboarding_accepted=False)

    report = sync_discord(REGISTRY, client, store, GUILD_ID)

    assert report.is_onboarding_applied is False
    assert report.errors == []
    assert report.created == 18


def test_온보딩_질문_구성은_고정_문구이고_infra와_역할_없는_프로젝트는_뺀다():
    registry = make_registry(make_project("elum", "이룸"), make_project("infra", "인프라"), SAMPLE)

    payload = build_onboarding_payload(registry, {"elum": "11", "infra": "22"}, notice_channel_id="33")

    assert payload == {
        "prompts": [{
            "type": 0, "title": "어떤 프로젝트 알림을 받을까요?", "single_select": False, "required": False,
            "in_onboarding": True,
            "options": [{"title": "이룸", "description": "이룸 상태·배포 알림", "role_ids": ["11"], "channel_ids": []}],
        }],
        "default_channel_ids": ["33"], "enabled": True, "mode": 0,
    }
    assert build_onboarding_payload(registry, {})["default_channel_ids"] == []
