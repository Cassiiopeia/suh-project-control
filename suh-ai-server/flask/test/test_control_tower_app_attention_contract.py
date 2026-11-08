"""앱 확인할 일 계약: JSON Schema 원본과 Flask 검증기가 모든 예시에 같은 판정을 내리는지, 검증기 규칙"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from service.control_tower.app_attention_validation import parse_attention_snapshot

ATTENTION_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "control-tower" / "attention"
EXAMPLE_FILES = sorted((ATTENTION_DIRECTORY / "examples").glob("*.json"))
SCHEMA = json.loads((ATTENTION_DIRECTORY / "attention-v1.schema.json").read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def _document(items: list, **overrides) -> dict:
    document = {
        "schema": "attention", "version": "1.0", "source": {"app": "elum-server"},
        "generated_at": "2026-11-08T12:00:00Z", "items": items,
    }
    document.update(overrides)
    return document


def _count_item(**overrides) -> dict:
    item = {"key": "feedback.new", "label": "새 의견", "kind": "count", "count": 1, "level": "info"}
    item.update(overrides)
    return item


def _is_validator_accepting(document) -> bool:
    result = parse_attention_snapshot(document)
    return result.errors == () and not result.dropped_items


def test_스키마_파일이_2020_12_규격으로_유효하다():
    """스키마 자체가 메타 스키마를 통과"""
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_예시_파일이_유효_4개_이상_무효_8개_이상이다():
    """예시 모음 개수 하한"""
    valid_count = len([path for path in EXAMPLE_FILES if path.name.startswith("valid_")])
    invalid_count = len([path for path in EXAMPLE_FILES if path.name.startswith("invalid_")])
    assert valid_count >= 4
    assert invalid_count >= 8


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=lambda path: path.name)
def test_모든_예시에서_스키마와_검증기의_판정이_같다(example_path):
    """항목 위반은 스키마 invalid <-> dropped_items 있음, 최상위 위반은 스키마 invalid <-> errors 있음"""
    document = json.loads(example_path.read_text(encoding="utf-8"))
    is_schema_valid = SCHEMA_VALIDATOR.is_valid(document)
    assert is_schema_valid == _is_validator_accepting(document)
    # 파일 이름 접두사가 스키마 판정과 일치 (예시 분류 오류 방지)
    assert is_schema_valid == example_path.name.startswith("valid_")


def test_항목이_100개를_넘으면_최상위_오류다():
    """101개는 생성해서 확인: 스키마와 검증기 모두 거부, 100개는 통과"""
    items = [_count_item(key=f"custom.item{index}") for index in range(101)]
    over_limit = _document(items)
    assert not SCHEMA_VALIDATOR.is_valid(over_limit)
    result = parse_attention_snapshot(over_limit)
    assert result.snapshot is None
    assert "too_many_items" in result.errors
    exactly_limit = _document(items[:100])
    assert SCHEMA_VALIDATOR.is_valid(exactly_limit)
    assert len(parse_attention_snapshot(exactly_limit).snapshot.items) == 100


def test_모르는_필드는_무시하고_모르는_kind는_항목을_유지한다():
    """모르는 kind는 count/value/state 없이 label·level·raw만 유지"""
    document = _document(
        [{"key": "custom.sync", "label": "동기화", "kind": "progress", "level": "warning", "percent": 40}],
        future_field=1,
    )
    result = parse_attention_snapshot(document)
    assert result.errors == () and result.dropped_items == ()
    item = result.snapshot.items[0]
    assert (item.kind, item.level, item.count, item.value, item.state) == ("progress", "warning", None, None, None)
    assert item.raw["percent"] == 40


def test_상대_admin_url은_기준_주소와_합치고_http_절대주소는_버린다():
    """기준 주소 없는 상대 경로, //host, 공백 포함도 버림 (항목은 유지)"""
    document = _document(
        [
            _count_item(key="a.relative", admin_url="/feedbacks?status=NEW"),
            _count_item(key="a.absolute", admin_url="https://other.example/x"),
            _count_item(key="a.insecure", admin_url="http://other.example/x"),
            _count_item(key="a.protocol_relative", admin_url="//evil.example/x"),
            _count_item(key="a.spaced", admin_url="/a b"),
        ],
        source={"app": "elum-server", "admin_base_url": "https://elum.example/admin/"},
    )
    result = parse_attention_snapshot(document)
    assert result.dropped_items == ()
    url_by_key = {item.key: item.admin_url for item in result.snapshot.items}
    assert url_by_key == {
        "a.relative": "https://elum.example/admin/feedbacks?status=NEW",
        "a.absolute": "https://other.example/x",
        "a.insecure": None,
        "a.protocol_relative": None,
        "a.spaced": None,
    }
    without_base = parse_attention_snapshot(_document([_count_item(admin_url="/feedbacks")]))
    assert without_base.snapshot.items[0].admin_url is None


def test_항목_단위_위반은_그_항목만_버리고_사유를_남긴다():
    """key 모양 틀림 > #순번, key 중복 > 뒤의 것 버림, 나머지 항목은 유지"""
    document = _document([
        _count_item(key="job.failed", count=-5),
        _count_item(key="feedback.new", count=2),
        "문자열 항목",
        _count_item(key="feedback.new", count=9),
        _count_item(key="Bad.Key"),
        _count_item(key="report.unresolved", count=4, total=10),
    ])
    result = parse_attention_snapshot(document)
    assert result.errors == ()
    assert [item.key for item in result.snapshot.items] == ["feedback.new", "report.unresolved"]
    assert result.snapshot.items[0].count == 2
    assert result.dropped_items == (
        ("job.failed", "invalid_count"), ("#2", "not_object"),
        ("feedback.new", "duplicate_key"), ("#4", "invalid_key"),
    )


def test_주_버전이_1이_아니면_최상위_오류다():
    """부 버전은 무시, 주 버전 2는 unsupported_version, 형식 불량은 invalid_version"""
    assert parse_attention_snapshot(_document([], version="1.7")).errors == ()
    unsupported = parse_attention_snapshot(_document([], version="2.0"))
    assert unsupported.snapshot is None
    assert unsupported.errors == ("unsupported_version",)
    assert parse_attention_snapshot(_document([], version="v1")).errors == ("invalid_version",)


def test_스냅샷_값이_종류별로_정확히_변환된다():
    """count/total, gauge/limit/unit, state, 시각 UTC 변환, 환경 기본값 production"""
    document = _document(
        [
            _count_item(total=182, latest_at="2026-11-08T21:00:00+09:00", group="사용자", detail="2일 전"),
            {"key": "budget.daily", "label": "비용", "kind": "gauge", "value": 8, "limit": 10, "unit": "USD", "level": "warning"},
            {"key": "ai.provider", "label": "AI", "kind": "state", "state": "down", "level": "critical"},
        ],
        poll_after_seconds=30, generated_at="2026-11-08T12:00:00.123456789Z",
    )
    snapshot = parse_attention_snapshot(document).snapshot
    assert snapshot.environment == "production"
    assert snapshot.major_version == 1
    assert snapshot.poll_after_seconds == 30
    assert snapshot.generated_at == datetime(2026, 11, 8, 12, 0, 0, 123456, tzinfo=timezone.utc)
    count_item, gauge_item, state_item = snapshot.items
    assert (count_item.count, count_item.total, count_item.group, count_item.detail) == (1, 182, "사용자", "2일 전")
    assert count_item.latest_at == datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    assert (gauge_item.value, gauge_item.limit, gauge_item.unit) == (8.0, 10.0, "USD")
    assert state_item.state == "down"


@pytest.mark.parametrize("document", [None, [], "attention", 3])
def test_객체가_아닌_본문은_최상위_오류다(document):
    """JSON이 객체가 아니면 not_object"""
    result = parse_attention_snapshot(document)
    assert result.snapshot is None and result.errors == ("not_object",)


def test_원본_본문을_수정하지_않는다():
    """검증은 순수 함수: 입력 문서가 그대로"""
    document = _document([_count_item(admin_url="/x")], source={"app": "a", "admin_base_url": "https://a.example"})
    before = copy.deepcopy(document)
    parse_attention_snapshot(document)
    assert document == before
