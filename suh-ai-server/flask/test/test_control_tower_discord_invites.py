"""관제소 프로젝트 초대: 숨긴 프로젝트 온보딩 제외, 초대 발급·다시 만들기·API, 초대 귀속(단일·모호·제외 대상·재기동·실패)"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    REGISTRY, FakePoller, _snapshot, dispatcher, make_app, store,
)
from control_tower_discord_fakes import ELUM, SAMPLE, make_registry
from service.control_tower import runtime as runtime_module
from service.control_tower.discord_client import DiscordError
from service.control_tower.discord_invite_attribution import InviteAttributionStep
from service.control_tower.discord_invites import InviteError, ensure_project_invite
from service.control_tower.discord_sync import build_onboarding_payload
from service.control_tower.meta_keys import META_KEY_INVITE_LAST_CHECKED_AT
from service.control_tower.runtime import ControlTowerRuntime
from service.control_tower.store import ControlTowerStore

NOW = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)
ELUM_ROLE_ID = "501"
SAMPLE_ROLE_ID = "502"


class FakeInviteDiscord:
    """초대·멤버 메모리 디스코드: 초대 사용 횟수, 멤버 목록, 역할 부여 기록, 실패 주입"""

    def __init__(self):
        self.invites: dict[str, dict] = {}
        self.members: list[dict] = []
        self.role_grants: list[tuple[str, str]] = []
        self.deleted_codes: list[str] = []
        self.failing_operation: str | None = None
        self._next_code = 0

    def _fail_if_requested(self, operation: str) -> None:
        if self.failing_operation == operation:
            raise DiscordError(403, "Missing Permissions")

    def create_invite(self, channel_id, max_age=0, max_uses=0, unique=True):
        self._fail_if_requested("create_invite")
        self._next_code += 1
        code = f"code{self._next_code}"
        self.invites[code] = {"code": code, "uses": 0, "channel": {"id": channel_id}}
        return dict(self.invites[code])

    def delete_invite(self, code):
        self._fail_if_requested("delete_invite")
        if code not in self.invites:
            raise DiscordError(404, "Unknown Invite")
        self.deleted_codes.append(code)
        del self.invites[code]

    def list_guild_invites(self):
        self._fail_if_requested("list_guild_invites")
        return [dict(invite) for invite in self.invites.values()]

    def list_members(self, after=None, limit=1000):
        self._fail_if_requested("list_members")
        ordered = sorted(self.members, key=lambda member: int(member["user"]["id"]))
        if after is not None:
            ordered = [member for member in ordered if int(member["user"]["id"]) > int(after)]
        return [dict(member) for member in ordered[:limit]]

    def add_member_role(self, user_id, role_id):
        self._fail_if_requested("add_member_role")
        self.role_grants.append((user_id, role_id))
        member = next(member for member in self.members if member["user"]["id"] == user_id)
        member["roles"] = list(member["roles"]) + [role_id]

    # ---- 테스트 도우미 ----

    def join(self, user_id: str, joined_at: datetime, invite_code: str | None = None, is_bot: bool = False,
             roles: tuple[str, ...] = ()) -> None:
        self.members.append({"user": {"id": user_id, "bot": is_bot}, "roles": list(roles),
                             "joined_at": joined_at.isoformat()})
        if invite_code is not None:
            self.invites[invite_code]["uses"] += 1


@pytest.fixture
def discord():
    return FakeInviteDiscord()


@pytest.fixture
def bound_store(store):
    """elum·sample 동기화 완료 상태 (status 채널 + member 역할 바인딩)"""
    for project_id, channel_id, role_id in (("elum", "701", ELUM_ROLE_ID), ("sample", "702", SAMPLE_ROLE_ID)):
        store.set_binding(project_id, "status", channel_id)
        store.set_binding(project_id, "role:member", role_id)
    return store


def _issue(discord, store, project_id: str, should_regenerate: bool = False, now: datetime = NOW):
    return ensure_project_invite(discord, store, project_id, should_regenerate, now)


# ---- 숨긴 프로젝트 온보딩 제외 ----

def test_숨긴_프로젝트는_온보딩_옵션에서_빠진다():
    registry = make_registry(replace(ELUM, is_hidden=True), SAMPLE)
    payload = build_onboarding_payload(registry, {"elum": ELUM_ROLE_ID, "sample": SAMPLE_ROLE_ID})

    titles = [option["title"] for prompt in payload["prompts"] for option in prompt["options"]]
    assert titles == ["샘플"]


# ---- 초대 발급 ----

def test_초대는_status_채널에_만들고_다시_부르면_같은_초대를_준다(discord, bound_store):
    first = _issue(discord, bound_store, "elum")
    second = _issue(discord, bound_store, "elum")

    assert first.url == "https://discord.gg/code1" and first.channel_id == "701"
    assert second.invite_code == "code1" and list(discord.invites) == ["code1"]


def test_다시_만들기는_이전_초대를_지우고_사용_횟수를_0부터_센다(discord, bound_store):
    _issue(discord, bound_store, "elum")
    bound_store.update_invite_uses_seen("elum", "code1", 4)

    regenerated = _issue(discord, bound_store, "elum", should_regenerate=True)

    assert discord.deleted_codes == ["code1"] and regenerated.invite_code == "code2"
    assert regenerated.uses_seen == 0


def test_다시_만들기에서_이전_초대가_이미_없으면_그대로_새로_만든다(discord, bound_store):
    _issue(discord, bound_store, "elum")
    del discord.invites["code1"]

    assert _issue(discord, bound_store, "elum", should_regenerate=True).invite_code == "code2"


def test_동기화_전_프로젝트_초대는_409_디스코드_실패는_502(discord, store, bound_store):
    with pytest.raises(InviteError) as not_synced:
        _issue(discord, store, "unknown")
    discord.failing_operation = "create_invite"
    with pytest.raises(InviteError) as failed:
        _issue(discord, bound_store, "elum")

    assert (not_synced.value.code, not_synced.value.status_code) == ("discord_not_synced", 409)
    assert (failed.value.code, failed.value.status_code, failed.value.discord_status_code) == ("discord_failed", 502, 403)
    assert bound_store.get_project_invite("elum") is None


# ---- 초대 API ----

@pytest.fixture
def invite_client(bound_store, dispatcher, discord):
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, bound_store, dispatcher, poller=FakePoller(_snapshot()),
        discord_client_provider=lambda: discord, guild_id="9000", file_registry_provider=lambda: REGISTRY))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


def test_초대_API는_발급_재사용_다시_만들기와_manage_invite_url을_준다(invite_client):
    assert invite_client.get("/control/manage").get_json()["projects"][0]["invite_url"] is None

    created = invite_client.post("/control/projects/elum/invite")
    reused = invite_client.post("/control/projects/elum/invite").get_json()
    regenerated = invite_client.post("/control/projects/elum/invite?regenerate=1").get_json()

    assert created.status_code == 200
    assert created.get_json()["url"] == "https://discord.gg/code1" and reused["code"] == "code1"
    assert regenerated["code"] == "code2" and regenerated["created_at"]
    assert invite_client.get("/control/manage").get_json()["projects"][0]["invite_url"] == "https://discord.gg/code2"


def test_초대_API는_모르는_프로젝트_404_디스코드_미설정_503(invite_client, bound_store, dispatcher):
    assert invite_client.post("/control/projects/nope/invite").status_code == 404
    runtime_module.set_runtime(ControlTowerRuntime(lambda: REGISTRY, bound_store, dispatcher))
    response = invite_client.post("/control/projects/elum/invite")
    assert (response.status_code, response.get_json()["error"]) == (503, "discord_not_configured")


# ---- 초대 귀속 ----

def _step_with_invites(discord, store):
    """elum·sample 초대 발급 > 확인 시각 = NOW"""
    _issue(discord, store, "elum")
    _issue(discord, store, "sample")
    store.set_meta(META_KEY_INVITE_LAST_CHECKED_AT, NOW.isoformat())
    return InviteAttributionStep(discord, store)


def test_한_프로젝트_초대만_늘면_새_멤버에게_그_member_역할을_준다(discord, bound_store):
    step = _step_with_invites(discord, bound_store)
    discord.join("11", NOW + timedelta(seconds=20), invite_code="code1")

    step.run(NOW + timedelta(minutes=1))

    assert discord.role_grants == [("11", ELUM_ROLE_ID)]
    assert bound_store.get_project_invite("elum").uses_seen == 1


def test_여러_프로젝트_초대가_같은_틱에_늘면_아무_역할도_주지_않는다(discord, bound_store, caplog):
    step = _step_with_invites(discord, bound_store)
    discord.join("11", NOW + timedelta(seconds=10), invite_code="code1")
    discord.join("12", NOW + timedelta(seconds=20), invite_code="code2")

    step.run(NOW + timedelta(minutes=1))

    assert discord.role_grants == []
    assert "[control-tower discord invite] ambiguous join" in caplog.text
    assert bound_store.get_project_invite("elum").uses_seen == 1
    assert bound_store.get_project_invite("sample").uses_seen == 1


def test_이미_member_역할이_있거나_봇이거나_확인_전_가입한_멤버는_건너뛴다(discord, bound_store):
    step = _step_with_invites(discord, bound_store)
    discord.join("10", NOW - timedelta(minutes=5))
    discord.join("11", NOW + timedelta(seconds=5), is_bot=True)
    discord.join("12", NOW + timedelta(seconds=6), roles=(SAMPLE_ROLE_ID,))
    discord.join("13", NOW + timedelta(seconds=30), invite_code="code1")
    discord.join("14", NOW + timedelta(seconds=40))

    step.run(NOW + timedelta(minutes=1))

    # 늘어난 1명만, 오래된 순 (13 > 14)
    assert discord.role_grants == [("13", ELUM_ROLE_ID)]


def test_사용_횟수_증가가_없으면_멤버를_조회하지_않는다(discord, bound_store):
    step = _step_with_invites(discord, bound_store)
    discord.failing_operation = "list_members"

    step.run(NOW + timedelta(minutes=1))

    assert bound_store.get_meta(META_KEY_INVITE_LAST_CHECKED_AT).startswith("2026-11-07T03:01")


def test_재기동_후에도_기록한_사용_횟수로_다시_부여하지_않는다(discord, bound_store, tmp_path):
    step = _step_with_invites(discord, bound_store)
    discord.join("11", NOW + timedelta(seconds=20), invite_code="code1")
    step.run(NOW + timedelta(minutes=1))
    bound_store.close()

    reopened_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    reopened_store.initialize()
    discord.members[0]["roles"] = []  # 역할이 빠졌어도 사용 횟수가 그대로면 재부여 없음
    InviteAttributionStep(discord, reopened_store).run(NOW + timedelta(minutes=2))

    assert discord.role_grants == [("11", ELUM_ROLE_ID)]
    assert reopened_store.get_project_invite("elum").uses_seen == 1
    reopened_store.close()


def test_디스코드_실패는_예외_없이_기록만_하고_다음_틱에_재시도한다(discord, bound_store, caplog):
    step = _step_with_invites(discord, bound_store)
    discord.join("11", NOW + timedelta(seconds=20), invite_code="code1")
    discord.failing_operation = "add_member_role"

    step.run(NOW + timedelta(minutes=1))

    assert "attribution failed : status 403" in caplog.text
    assert bound_store.get_project_invite("elum").uses_seen == 0
    discord.failing_operation = None
    step.run(NOW + timedelta(minutes=2))
    assert discord.role_grants == [("11", ELUM_ROLE_ID)]


def test_초대가_없으면_디스코드를_호출하지_않는다(discord, store):
    discord.failing_operation = "list_guild_invites"
    InviteAttributionStep(discord, store).run(NOW)
    assert store.get_meta(META_KEY_INVITE_LAST_CHECKED_AT) is None
