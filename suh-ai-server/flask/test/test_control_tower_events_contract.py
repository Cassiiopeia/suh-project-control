"""앱 이벤트 계약: 예시 파일이 Flask 검증기 판정과 일치, 스키마 상한이 검증기 상수와 일치"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.control_tower import event_dispatcher
from service.control_tower.event_dispatcher import EVENT_KINDS, EVENT_SEVERITIES, validate_event_payload

EVENTS_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "control-tower" / "events"
EXAMPLE_FILES = sorted((EVENTS_DIRECTORY / "examples").glob("*.json"))
SCHEMA = json.loads((EVENTS_DIRECTORY / "events-v1.schema.json").read_text(encoding="utf-8"))
# 예시 판정용 허용 종류: 기본 종류 + 사용자 정의 종류 1개
ALLOWED_KINDS = frozenset(EVENT_KINDS) | {"claude-code"}
FIELD_SCHEMA = SCHEMA["properties"]["fields"]


def _load_example(example_path: Path) -> dict:
    return json.loads(example_path.read_text(encoding="utf-8"))


def test_예시_파일이_유효_2개_이상_무효_2개_이상이다():
    """예시 모음 개수 하한"""
    assert len([path for path in EXAMPLE_FILES if path.name.startswith("valid_")]) >= 2
    assert len([path for path in EXAMPLE_FILES if path.name.startswith("invalid_")]) >= 2


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=lambda path: path.name)
def test_예시_접두사와_검증기_판정이_같다(example_path):
    """valid_* > 잘못된 필드 없음, invalid_* > 잘못된 필드 있음"""
    invalid_fields = validate_event_payload(_load_example(example_path), ALLOWED_KINDS)
    assert (invalid_fields == []) == example_path.name.startswith("valid_")


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=lambda path: path.name)
def test_예시에서_스키마와_검증기의_판정이_같다(example_path):
    """스키마 검증 결과 <-> 검증기 결과 (jsonschema 미설치면 skip)"""
    jsonschema = pytest.importorskip("jsonschema")
    document = _load_example(example_path)
    # kind는 프로젝트별 목록이라 스키마는 형태만 보고, 허용 종류는 검증기만 판단
    is_schema_valid = jsonschema.Draft202012Validator(SCHEMA).is_valid(document)
    assert is_schema_valid == (validate_event_payload(document, ALLOWED_KINDS) == [])


def test_스키마가_2020_12_규격으로_유효하다():
    """스키마 자체가 메타 스키마를 통과 (jsonschema 미설치면 skip)"""
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_스키마_상한이_검증기_상수와_같다():
    """단일 원본 유지: 스키마 길이·개수 상한 == event_dispatcher 상수 (어긋나면 실패)"""
    properties = SCHEMA["properties"]
    assert properties["severity"]["enum"] == list(EVENT_SEVERITIES)
    assert properties["title"]["minLength"] == event_dispatcher.TITLE_MIN_LENGTH
    assert properties["title"]["maxLength"] == event_dispatcher.TITLE_MAX_LENGTH
    assert properties["body"]["maxLength"] == event_dispatcher.BODY_MAX_LENGTH
    assert properties["url"]["maxLength"] == event_dispatcher.URL_MAX_LENGTH
    assert event_dispatcher.ALLOWED_URL_PREFIX == "https://"
    assert properties["url"]["pattern"] == "^" + event_dispatcher.ALLOWED_URL_PREFIX
    assert FIELD_SCHEMA["maxItems"] == event_dispatcher.EVENT_FIELDS_MAX_COUNT
    field_properties = FIELD_SCHEMA["items"]["properties"]
    assert field_properties["name"]["maxLength"] == event_dispatcher.EVENT_FIELD_NAME_MAX_LENGTH
    assert field_properties["value"]["maxLength"] == event_dispatcher.EVENT_FIELD_VALUE_MAX_LENGTH
    assert field_properties["name"]["minLength"] == 1 and field_properties["value"]["minLength"] == 1
    assert set(SCHEMA["required"]) == {"project", "kind", "severity", "title"}


def test_기본_종류가_문서_스키마_설명과_같다():
    """스키마 kind 설명에 기본 종류 전부 포함"""
    description = SCHEMA["properties"]["kind"]["description"]
    assert all(kind in description for kind in EVENT_KINDS)
