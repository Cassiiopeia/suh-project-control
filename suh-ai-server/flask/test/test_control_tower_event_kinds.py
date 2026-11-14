"""관제소 사용자 정의 알림 종류: 입력 검증, 저장소 왕복, 실효 등록 정보 병합"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from control_tower_admin_fixtures import REGISTRY, store  # noqa: F401 (pytest 픽스처 재노출)
from service.control_tower.event_dispatcher import EventDispatcher
from service.control_tower.event_kind_validation import parse_new_event_kind
from service.control_tower.override_models import CustomProject, RegistryOverrides
from service.control_tower.registry_models import DiscordPolicy, EventKindSpec
from service.control_tower.registry_overrides import merge_overrides

NOW = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
# 기본 역할 목록 (member, dev)
DISCORD = DiscordPolicy()


def test_parse_new_event_kind_defaults():
    spec, invalid_fields = parse_new_event_kind({"kind": "claude-code"}, DISCORD)

    assert spec == EventKindSpec("claude-code", "claude-code", ("dev",))
    assert invalid_fields == []


@pytest.mark.parametrize("kind", ["report", "alert", "info", "_category", "role:dev", "status", "digest"])
def test_parse_new_event_kind_rejects_reserved(kind):
    assert parse_new_event_kind({"kind": kind}, DISCORD) == (None, ["kind"])


@pytest.mark.parametrize("kind", ["Claude", "a", "x" * 33, "1abc", "", None, 5])
def test_parse_new_event_kind_rejects_bad_format(kind):
    assert parse_new_event_kind({"kind": kind}, DISCORD) == (None, ["kind"])


def test_parse_new_event_kind_visible_to():
    spec, invalid_fields = parse_new_event_kind({"kind": "build", "visible_to": ["member", "dev"]}, DISCORD)
    assert (spec.visible_to, invalid_fields) == (("member", "dev"), [])

    spec, invalid_fields = parse_new_event_kind({"kind": "build", "visible_to": []}, DISCORD)
    assert (spec.visible_to, invalid_fields) == ((), [])

    for bad in (["admin"], ["everyone"], "dev", ["dev", "dev"], [["dev"]], [{}], [None]):
        assert parse_new_event_kind({"kind": "build", "visible_to": bad}, DISCORD) == (None, ["visible_to"])


def test_parse_new_event_kind_channel_name_length():
    assert parse_new_event_kind({"kind": "build", "channel_name": "가" * 40}, DISCORD)[1] == []
    assert parse_new_event_kind({"kind": "build", "channel_name": "가" * 41}, DISCORD) == (None, ["channel_name"])
    assert parse_new_event_kind({"kind": "build", "channel_name": ""}, DISCORD) == (None, ["channel_name"])


def test_parse_new_event_kind_rejects_whitespace_only_channel_name_and_strips():
    assert parse_new_event_kind({"kind": "build", "channel_name": "   "}, DISCORD) == (None, ["channel_name"])
    spec, invalid_fields = parse_new_event_kind({"kind": "build", "channel_name": "  빌드 "}, DISCORD)
    assert (spec.channel_name, invalid_fields) == ("빌드", [])


def test_parse_new_event_kind_visible_roles_follow_registry_roles():
    custom_roles = DiscordPolicy(role_names={"member": "{project}", "qa": "{project}-qa"})

    spec, invalid_fields = parse_new_event_kind({"kind": "build", "visible_to": ["qa"]}, custom_roles)
    assert (spec.visible_to, invalid_fields) == (("qa",), [])
    assert parse_new_event_kind({"kind": "build", "visible_to": ["dev"]}, custom_roles) == (None, ["visible_to"])
    # dev 역할이 없으면 기본 공개 대상은 관리자만
    assert parse_new_event_kind({"kind": "build"}, custom_roles)[0].visible_to == ()


def test_parse_new_event_kind_reports_all_invalid_fields():
    assert parse_new_event_kind({"kind": "Bad", "channel_name": "x" * 41, "visible_to": "dev"}, DISCORD) == (
        None, ["kind", "channel_name", "visible_to"])


def test_store_insert_list_delete(store):
    first = EventKindSpec("claude-code", "클로드", ("dev",))
    second = EventKindSpec("build", "build", ())

    assert store.insert_project_event_kind("elum", first, NOW) is True
    assert store.insert_project_event_kind("elum", second, NOW) is True
    assert store.list_project_event_kinds() == {"elum": (first, second)}

    assert store.insert_project_event_kind("elum", first, NOW) is False
    assert store.delete_project_event_kind("elum", "claude-code") is True
    assert store.delete_project_event_kind("elum", "claude-code") is False
    assert store.list_project_event_kinds() == {"elum": (second,)}
    assert store.load_registry_overrides().project_event_kinds == {"elum": (second,)}


def test_merge_overrides_attaches_event_kinds():
    spec = EventKindSpec("claude-code", "claude-code", ("dev",))
    overrides = RegistryOverrides(
        custom_projects=(CustomProject("extra", "추가"),),
        project_event_kinds={"elum": (spec,), "extra": (spec,)})

    projects = {project.id: project for project in merge_overrides(REGISTRY, overrides).projects}

    assert projects["elum"].event_kinds == (spec,)
    assert projects["extra"].event_kinds == (spec,)
    assert merge_overrides(REGISTRY, RegistryOverrides()).projects[0].event_kinds == ()


@pytest.mark.parametrize("payload", [None, "claude-code", ["kind"], 5])
def test_parse_new_event_kind_rejects_non_dict_payload(payload):
    assert parse_new_event_kind(payload, DISCORD) == (None, ["kind"])


def test_dispatcher_accepts_kind_right_after_store_insert(store):
    # 등록 정보 캐시 갱신 없이 저장소 추가만으로 접수 (폴러 주기 지연 없음), 삭제도 바로 반영
    dispatcher = EventDispatcher(store, lambda: None, "https://status.example.com")
    payload = {"kind": "claude-code", "severity": "info", "title": "코드 발급"}

    assert dispatcher.accept_event("elum", payload, NOW)[1]["error"] == "unknown_kind"
    store.insert_project_event_kind("elum", EventKindSpec("claude-code", "claude-code", ("dev",)), NOW)
    assert dispatcher.accept_event("elum", payload, NOW)[0] == 202
    assert store.list_event_kind_names_of_project("sample") == frozenset()
    store.delete_project_event_kind("elum", "claude-code")
    assert dispatcher.accept_event("elum", payload, NOW)[1]["error"] == "unknown_kind"
