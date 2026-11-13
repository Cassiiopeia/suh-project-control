"""관제소 사용자 정의 알림 종류: 입력 검증, 저장소 왕복, 실효 등록 정보 병합"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from control_tower_admin_fixtures import REGISTRY, store  # noqa: F401 (pytest 픽스처 재노출)
from service.control_tower.event_kind_validation import parse_new_event_kind
from service.control_tower.override_models import CustomProject, RegistryOverrides
from service.control_tower.registry_models import EventKindSpec
from service.control_tower.registry_overrides import merge_overrides

NOW = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)


def test_parse_new_event_kind_defaults():
    spec, invalid_fields = parse_new_event_kind({"kind": "claude-code"})

    assert spec == EventKindSpec("claude-code", "claude-code", ("dev",))
    assert invalid_fields == []


@pytest.mark.parametrize("kind", ["report", "alert", "info", "_category", "role:dev", "status", "digest"])
def test_parse_new_event_kind_rejects_reserved(kind):
    assert parse_new_event_kind({"kind": kind}) == (None, ["kind"])


@pytest.mark.parametrize("kind", ["Claude", "a", "x" * 33, "1abc", "", None, 5])
def test_parse_new_event_kind_rejects_bad_format(kind):
    assert parse_new_event_kind({"kind": kind}) == (None, ["kind"])


def test_parse_new_event_kind_visible_to():
    spec, invalid_fields = parse_new_event_kind({"kind": "build", "visible_to": ["member", "dev"]})
    assert (spec.visible_to, invalid_fields) == (("member", "dev"), [])

    spec, invalid_fields = parse_new_event_kind({"kind": "build", "visible_to": []})
    assert (spec.visible_to, invalid_fields) == ((), [])

    for bad in (["admin"], ["everyone"], "dev", ["dev", "dev"], [["dev"]], [{}], [None]):
        assert parse_new_event_kind({"kind": "build", "visible_to": bad}) == (None, ["visible_to"])


def test_parse_new_event_kind_channel_name_length():
    assert parse_new_event_kind({"kind": "build", "channel_name": "가" * 40})[1] == []
    assert parse_new_event_kind({"kind": "build", "channel_name": "가" * 41}) == (None, ["channel_name"])
    assert parse_new_event_kind({"kind": "build", "channel_name": ""}) == (None, ["channel_name"])


def test_parse_new_event_kind_reports_all_invalid_fields():
    assert parse_new_event_kind({"kind": "Bad", "channel_name": "x" * 41, "visible_to": "dev"}) == (
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
    assert parse_new_event_kind(payload) == (None, ["kind"])
