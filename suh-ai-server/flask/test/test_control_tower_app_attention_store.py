"""앱 확인할 일 저장소: 왕복, 소스 삭제 연쇄, 값 변경 시에만 이력, 동시 반영 보호, 보관 정리"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from service.control_tower.app_attention_store import (
    AttentionItemAlertState, AttentionItemOverride, AttentionSource, StoredAttentionItem,
    new_attention_source_state)
from service.control_tower.store import ControlTowerStore

PROJECT_ID = "elum"
SOURCE_ID = "api"
BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def _source(source_id: str = SOURCE_ID, url: str = "https://elum.example/attention") -> AttentionSource:
    return AttentionSource(PROJECT_ID, source_id, url, True, "both", 60, 5, 300, BASE_TIME, BASE_TIME)


def _item(key: str = "feedback.new", count: int = 3, total: int = 10, level: str = "info",
          source_id: str = SOURCE_ID) -> StoredAttentionItem:
    return StoredAttentionItem(
        PROJECT_ID, source_id, key, "count", "새 의견", level, "사용자", "처리 전 의견", "https://elum.example/admin",
        BASE_TIME, "2일 전", count, total, None, None, None, None, '{"key": "feedback.new"}', BASE_TIME, BASE_TIME, None)


def _commit(store, items=(), missing_keys=(), alert_states=(), now=BASE_TIME, generated_at=BASE_TIME,
            expected=None, source_id=SOURCE_ID) -> bool:
    state = dataclasses.replace(new_attention_source_state(PROJECT_ID, source_id),
                                last_generated_at=generated_at, is_baseline_done=True, app="elum-server")
    return store.commit_attention_result(PROJECT_ID, source_id, state, list(items), list(missing_keys),
                                         list(alert_states), now, expected)


def _history_count(store, key: str = "feedback.new", source_id: str = SOURCE_ID) -> int:
    return store._connection().execute(
        'SELECT COUNT(*) FROM app_attention_history WHERE "key" = ? AND source_id = ?', (key, source_id)).fetchone()[0]


def _row_count(store, table: str) -> int:
    return store._connection().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_소스_저장과_조회가_왕복하고_다시_저장하면_설정만_바뀐다(store):
    """소스 upsert 왕복: created_at은 처음 값 유지, 나머지는 교체"""
    store.save_attention_source(_source())
    later = BASE_TIME + timedelta(hours=1)
    store.save_attention_source(dataclasses.replace(_source(url="https://new.example/a"), created_at=later,
                                                    updated_at=later, is_enabled=False))
    loaded = store.get_attention_source(PROJECT_ID, SOURCE_ID)
    assert loaded.url == "https://new.example/a"
    assert loaded.is_enabled is False
    assert loaded.created_at == BASE_TIME and loaded.updated_at == later
    assert store.get_attention_source(PROJECT_ID, "none") is None
    assert [source.source_id for source in store.list_attention_sources()] == [SOURCE_ID]


def test_수집_결과를_반영하면_상태_항목_알림_기준이_왕복한다(store):
    """commit 후 상태·항목(예약어 열 포함)·알림 기준을 그대로 읽는다"""
    store.save_attention_source(_source())
    gauge = dataclasses.replace(_item("budget.daily"), kind="gauge", count=None, total=None, value=8.2, limit=10.0,
                                unit="USD")
    alert = AttentionItemAlertState(PROJECT_ID, SOURCE_ID, "feedback.new", BASE_TIME, 10, 3, "info", True, 2)
    assert _commit(store, [_item(), gauge], alert_states=[alert]) is True
    state = store.get_attention_source_state(PROJECT_ID, SOURCE_ID)
    assert state.last_generated_at == BASE_TIME and state.is_baseline_done is True and state.next_due_at is None
    items = store.load_attention_items(PROJECT_ID, SOURCE_ID)
    assert items["feedback.new"].group == "사용자" and items["feedback.new"].count == 3
    assert items["budget.daily"].limit == 10.0 and items["budget.daily"].value == 8.2
    assert items["feedback.new"].latest_at == BASE_TIME and items["feedback.new"].missing_since is None
    assert store.load_attention_alert_states(PROJECT_ID, SOURCE_ID)["feedback.new"] == alert
    assert len(store.load_all_attention_items()) == 2


def test_알림_기준은_딕셔너리로도_받는다(store):
    """Task 3 반환 형태(key > 상태 딕셔너리) 그대로 저장"""
    store.save_attention_source(_source())
    alert = AttentionItemAlertState(PROJECT_ID, SOURCE_ID, "feedback.new", pending_new_count=4)
    state = new_attention_source_state(PROJECT_ID, SOURCE_ID)
    store.commit_attention_result(PROJECT_ID, SOURCE_ID, state, [], [], {"feedback.new": alert}, BASE_TIME, None)
    assert store.load_attention_alert_states(PROJECT_ID, SOURCE_ID)["feedback.new"].pending_new_count == 4


def test_항목_설정이_왕복하고_전부_비어_있으면_기본값이다(store):
    """override 저장·조회: 모두 None = 앱 값/기본 규칙"""
    store.save_attention_override(AttentionItemOverride(PROJECT_ID, SOURCE_ID, "feedback.new", True, "의견",
                                                        "warning", "threshold", 5.0, "attention"))
    store.save_attention_override(AttentionItemOverride(PROJECT_ID, SOURCE_ID, "budget.daily"))
    overrides = store.load_attention_overrides(PROJECT_ID, SOURCE_ID)
    assert overrides["feedback.new"] == AttentionItemOverride(PROJECT_ID, SOURCE_ID, "feedback.new", True, "의견",
                                                              "warning", "threshold", 5.0, "attention")
    assert overrides["budget.daily"].is_hidden is None and overrides["budget.daily"].threshold is None


def test_소스를_삭제하면_상태_항목_설정_알림_이력이_모두_사라지고_같은_id로_다시_등록하면_비어_있다(store):
    """소스 삭제 연쇄 + 재등록 시 이전 흔적 없음 (다른 소스는 보존)"""
    store.save_attention_source(_source())
    store.save_attention_source(_source("batch"))
    store.save_attention_override(AttentionItemOverride(PROJECT_ID, SOURCE_ID, "feedback.new", True))
    alert = AttentionItemAlertState(PROJECT_ID, SOURCE_ID, "feedback.new", BASE_TIME, 10, 3, "info", False, 1)
    _commit(store, [_item()], alert_states=[alert])
    _commit(store, [_item(source_id="batch")], source_id="batch")

    assert store.delete_attention_source(PROJECT_ID, SOURCE_ID) is True
    assert store.delete_attention_source(PROJECT_ID, SOURCE_ID) is False
    store.save_attention_source(_source())

    assert store.get_attention_source_state(PROJECT_ID, SOURCE_ID) is None
    assert store.load_attention_items(PROJECT_ID, SOURCE_ID) == {}
    assert store.load_attention_overrides(PROJECT_ID, SOURCE_ID) == {}
    assert store.load_attention_alert_states(PROJECT_ID, SOURCE_ID) == {}
    assert _history_count(store) == 0
    assert list(store.load_attention_items(PROJECT_ID, "batch")) == ["feedback.new"]
    assert _history_count(store, source_id="batch") == 1


def test_값이_안_바뀌면_이력이_쌓이지_않고_바뀌면_1행씩_쌓인다(store):
    """history: 새 항목 1행, 같은 값 반복 0행, count/total/level 변경 각 1행"""
    store.save_attention_source(_source())
    _commit(store, [_item()])
    assert _history_count(store) == 1
    later = BASE_TIME + timedelta(minutes=1)
    _commit(store, [_item()], now=later, generated_at=later, expected=BASE_TIME)
    assert _history_count(store) == 1
    third = BASE_TIME + timedelta(minutes=2)
    _commit(store, [_item(total=11)], now=third, generated_at=third, expected=later)
    assert _history_count(store) == 2
    fourth = BASE_TIME + timedelta(minutes=3)
    _commit(store, [_item(total=11, level="warning")], now=fourth, generated_at=fourth, expected=third)
    assert _history_count(store) == 3
    items = store.load_attention_items(PROJECT_ID, SOURCE_ID)
    assert items["feedback.new"].updated_at == fourth and items["feedback.new"].first_seen_at == BASE_TIME


def test_기준_시각이_다르면_거짓을_돌려주고_아무것도_바꾸지_않는다(store):
    """expected_last_generated_at 불일치 = 다른 경로가 먼저 반영 > 상태·항목·이력 변화 없음"""
    store.save_attention_source(_source())
    _commit(store, [_item(count=3)])
    later = BASE_TIME + timedelta(minutes=1)
    assert _commit(store, [_item(count=9)], now=later, generated_at=later, expected=None) is False
    assert _commit(store, [_item(count=9)], now=later, generated_at=later,
                   expected=BASE_TIME - timedelta(seconds=1)) is False
    assert store.get_attention_source_state(PROJECT_ID, SOURCE_ID).last_generated_at == BASE_TIME
    assert store.load_attention_items(PROJECT_ID, SOURCE_ID)["feedback.new"].count == 3
    assert _history_count(store) == 1


def test_첫_반영은_기준_시각이_없어야_통과한다(store):
    """상태 행이 없으면 expected=None 만 통과"""
    store.save_attention_source(_source())
    assert _commit(store, [_item()], expected=BASE_TIME) is False
    assert _commit(store, [_item()], expected=None) is True


def test_삭제된_소스에는_결과를_반영하지_않는다(store):
    """수집 중 소스가 삭제되면 고아 행을 만들지 않음 (결과·실패 모두)"""
    assert _commit(store, [_item()]) is False
    store.record_attention_failure(PROJECT_ID, SOURCE_ID, new_attention_source_state(PROJECT_ID, SOURCE_ID))
    assert _row_count(store, "app_attention_item") == 0
    assert _row_count(store, "app_attention_source_state") == 0


def test_빠진_항목은_missing_since만_기록하고_처음_시각을_유지하며_다시_나타나면_비운다(store):
    """missing_keys: 최초 시각 유지, 재등장 시 NULL"""
    store.save_attention_source(_source())
    _commit(store, [_item(), _item("ai.provider")])
    first_missing = BASE_TIME + timedelta(minutes=1)
    _commit(store, [_item()], missing_keys=["ai.provider"], now=first_missing, generated_at=first_missing,
            expected=BASE_TIME)
    second_missing = BASE_TIME + timedelta(minutes=2)
    _commit(store, [_item()], missing_keys=["ai.provider"], now=second_missing, generated_at=second_missing,
            expected=first_missing)
    assert store.load_attention_items(PROJECT_ID, SOURCE_ID)["ai.provider"].missing_since == first_missing
    back = BASE_TIME + timedelta(minutes=3)
    _commit(store, [_item(), _item("ai.provider")], now=back, generated_at=back, expected=second_missing)
    reappeared = store.load_attention_items(PROJECT_ID, SOURCE_ID)["ai.provider"]
    assert reappeared.missing_since is None
    assert _history_count(store, "ai.provider") == 1  # 값이 같아 이력 추가 없음


def test_실패를_기록해도_항목과_반영된_스냅샷_값은_유지된다(store):
    """record_attention_failure: 시도 열만 갱신, etag·last_generated_at·항목 보존"""
    store.save_attention_source(_source())
    state = dataclasses.replace(new_attention_source_state(PROJECT_ID, SOURCE_ID), last_generated_at=BASE_TIME,
                                etag='"v1"', is_baseline_done=True)
    store.commit_attention_result(PROJECT_ID, SOURCE_ID, state, [_item()], [], [], BASE_TIME, None)
    stale_view = dataclasses.replace(new_attention_source_state(PROJECT_ID, SOURCE_ID), last_attempt_at=BASE_TIME,
                                     last_result="timeout", last_error="timeout", consecutive_failures=2,
                                     failure_alerted_at=BASE_TIME, next_due_at=BASE_TIME + timedelta(minutes=5))
    store.record_attention_failure(PROJECT_ID, SOURCE_ID, stale_view)
    saved = store.get_attention_source_state(PROJECT_ID, SOURCE_ID)
    assert (saved.last_result, saved.consecutive_failures, saved.failure_alerted_at) == ("timeout", 2, BASE_TIME)
    assert saved.next_due_at == BASE_TIME + timedelta(minutes=5)
    assert saved.etag == '"v1"' and saved.last_generated_at == BASE_TIME and saved.is_baseline_done is True
    assert list(store.load_attention_items(PROJECT_ID, SOURCE_ID)) == ["feedback.new"]


def test_상태_행이_없던_소스의_실패는_새로_기록한다(store):
    """push 전용 소스의 끊김 알림 기록 등 첫 상태 행 생성"""
    store.save_attention_source(_source())
    failed = dataclasses.replace(new_attention_source_state(PROJECT_ID, SOURCE_ID), last_result="error",
                                 consecutive_failures=1)
    store.record_attention_failure(PROJECT_ID, SOURCE_ID, failed)
    assert store.get_attention_source_state(PROJECT_ID, SOURCE_ID).last_result == "error"
    assert (PROJECT_ID, SOURCE_ID) in store.list_attention_source_states()


def test_빠진_지_7일_지난_항목만_정리되고_항목_설정은_남는다(store):
    """purge: missing_since 7일 초과 항목과 그 알림 기준 삭제, 6일 항목·보고 중 항목·override 보존"""
    store.save_attention_source(_source())
    alerts = [AttentionItemAlertState(PROJECT_ID, SOURCE_ID, key, pending_new_count=1)
              for key in ("old.item", "recent.item", "live.item")]
    _commit(store, [_item("old.item"), _item("recent.item"), _item("live.item")], alert_states=alerts)
    store.save_attention_override(AttentionItemOverride(PROJECT_ID, SOURCE_ID, "old.item", True))
    missing_time = BASE_TIME + timedelta(minutes=1)
    _commit(store, [_item("live.item")], missing_keys=["old.item"], now=BASE_TIME, generated_at=missing_time,
            expected=BASE_TIME)
    _commit(store, [_item("live.item")], missing_keys=["recent.item"], now=BASE_TIME + timedelta(days=1),
            generated_at=missing_time + timedelta(minutes=1), expected=missing_time)
    store.purge_app_attention(BASE_TIME + timedelta(days=7, seconds=1))
    assert sorted(store.load_attention_items(PROJECT_ID, SOURCE_ID)) == ["live.item", "recent.item"]
    assert sorted(store.load_attention_alert_states(PROJECT_ID, SOURCE_ID)) == ["live.item", "recent.item"]
    assert "old.item" in store.load_attention_overrides(PROJECT_ID, SOURCE_ID)


def test_이력은_90일_지나면_정리되고_store_purge가_함께_호출한다(store):
    """history 90일: 경계 안은 보존, ControlTowerStore.purge가 정리 호출"""
    store.save_attention_source(_source())
    _commit(store, [_item()])
    later = BASE_TIME + timedelta(days=30)
    _commit(store, [_item(count=4)], now=later, generated_at=later, expected=BASE_TIME)
    assert _history_count(store) == 2
    store.purge(BASE_TIME + timedelta(days=90, seconds=1))
    assert _history_count(store) == 1
    store.purge(later + timedelta(days=91))
    assert _history_count(store) == 0
    assert "feedback.new" in store.load_attention_items(PROJECT_ID, SOURCE_ID)  # 보고 중 항목은 남음


def test_기존_테이블이_있는_db를_다시_초기화해도_안전하다(store):
    """initialize 반복 실행 (CREATE IF NOT EXISTS)"""
    store.save_attention_source(_source())
    store.initialize()
    assert store.get_attention_source(PROJECT_ID, SOURCE_ID) is not None
