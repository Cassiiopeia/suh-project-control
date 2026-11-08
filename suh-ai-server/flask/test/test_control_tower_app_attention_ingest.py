"""앱 확인할 일 단일 처리 경로: 첫 성공 기준선, 재시작 후 폭주 없음, 늦은·동시 스냅샷 보호, 실패 시 항목 유지,
연동 끊김·복구, preview 무저장"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from service.control_tower.app_attention_fetch import FetchOutcome
from service.control_tower.app_attention_ingest import AppAttentionIngest
from service.control_tower.app_attention_store import AttentionSource
from service.control_tower.store import ControlTowerStore
from control_tower_discord_fakes import ELUM, make_registry
from control_tower_poller_fixtures import FakeDispatcher

BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
ITEM_TITLE = "이룸 확인할 일"


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


@pytest.fixture
def dispatcher():
    return FakeDispatcher()


@pytest.fixture
def source(store) -> AttentionSource:
    attention_source = AttentionSource("elum", "api", "https://elum.example/attention", True, "both", 60, 5, 300,
                                       BASE_TIME, BASE_TIME)
    store.save_attention_source(attention_source)
    return attention_source


def _ingest_service(store, dispatcher, down_projects=()) -> AppAttentionIngest:
    registry = make_registry(ELUM)
    return AppAttentionIngest(store, dispatcher, lambda: registry, lambda project_id: project_id in down_projects)


@pytest.fixture
def ingest(store, dispatcher) -> AppAttentionIngest:
    return _ingest_service(store, dispatcher)


def _feedback(count: int, total: int, **fields) -> dict:
    return {"key": "feedback.new", "label": "새 의견", "kind": "count", "count": count, "total": total,
            "level": "info", "admin_url": "https://elum.example/admin/feedbacks", **fields}


def _ok(minutes: int = 0, items=None, environment: str = "production", poll_after_seconds=None,
        etag: str | None = '"v1"') -> FetchOutcome:
    document = {"schema": "attention", "version": "1.0",
                "source": {"app": "elum-server", "app_version": "2.3.1", "environment": environment},
                "generated_at": (BASE_TIME + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
                "items": [_feedback(3, 10)] if items is None else items}
    if poll_after_seconds is not None:
        document["poll_after_seconds"] = poll_after_seconds
    return FetchOutcome("ok", document, etag, None)


def _at(minutes: float) -> datetime:
    return BASE_TIME + timedelta(minutes=minutes)


def _stored_count(store) -> int:
    return store.load_attention_items("elum", "api")["feedback.new"].count


def test_첫_성공은_기준선으로_저장만_하고_알리지_않는다(store, dispatcher, ingest, source):
    report = ingest.ingest(source, _ok(items=[_feedback(9, 50)]), _at(0))
    assert (report.result, report.notification_count) == ("ok", 0) and dispatcher.notifications == []
    state = store.get_attention_source_state("elum", "api")
    assert state.is_baseline_done and state.last_result == "ok" and state.etag == '"v1"'
    assert (state.app, state.app_version, state.environment) == ("elum-server", "2.3.1", "production")
    assert state.last_generated_at == _at(0) and _stored_count(store) == 9
    alert_state = store.load_attention_alert_states("elum", "api")["feedback.new"]
    assert (alert_state.project_id, alert_state.source_id) == ("elum", "api")


def test_기준선_뒤_새_건이_늘면_한_건으로_묶어_알린다(store, dispatcher, ingest, source):
    ingest.ingest(source, _ok(0), _at(0))
    report = ingest.ingest(source, _ok(1, items=[_feedback(5, 12)]), _at(1))
    assert report.notification_count == 1 and dispatcher.titles() == [ITEM_TITLE]
    notification = dispatcher.notifications[0]
    assert (notification.scope, notification.kind) == ("elum", "attention") and "+2" in notification.body


def test_DB를_유지한_재시작_직후_첫_처리는_알림이_폭주하지_않는다(store, dispatcher, source):
    _ingest_service(store, dispatcher).ingest(source, _ok(0, items=[_feedback(30, 300)]), _at(0))
    restarted = _ingest_service(store, dispatcher)
    report = restarted.ingest(source, _ok(5, items=[_feedback(30, 300)]), _at(5))
    assert report.notification_count == 0 and dispatcher.notifications == []


def test_비production_환경은_저장만_하고_알리지_않는다(store, dispatcher, ingest, source):
    ingest.ingest(source, _ok(0, environment="staging"), _at(0))
    ingest.ingest(source, _ok(1, items=[_feedback(8, 20)], environment="staging"), _at(1))
    assert dispatcher.notifications == [] and _stored_count(store) == 8


def test_반영한_시각_이하_스냅샷은_버리고_최신_값을_유지한다(store, dispatcher, ingest, source):
    ingest.ingest(source, _ok(5, items=[_feedback(5, 10)]), _at(5))
    for minutes in (5, 2):
        report = ingest.ingest(source, _ok(minutes, items=[_feedback(99, 99)]), _at(6))
        assert report.result == "stale"
    state = store.get_attention_source_state("elum", "api")
    assert _stored_count(store) == 5 and state.last_generated_at == _at(5)
    assert state.last_success_at == _at(6) and dispatcher.notifications == []


class _InterleavingStore:
    """상태를 읽은 뒤 저장 전에 다른 처리기가 끼어드는 상황 재현 (항목 설정 조회 시점에 1번 끼어듦)"""

    def __init__(self, store, interleave):
        self._store = store
        self._interleave = interleave

    def load_attention_overrides(self, project_id, source_id):
        interleave, self._interleave = self._interleave, None
        if interleave is not None:
            interleave()
        return self._store.load_attention_overrides(project_id, source_id)

    def __getattr__(self, name):
        return getattr(self._store, name)


def test_다른_처리기와_동시에_반영되면_밀린_스냅샷은_버리고_발송하지_않는다(store, dispatcher, source):
    _ingest_service(store, dispatcher).ingest(source, _ok(0), _at(0))
    other = _ingest_service(store, dispatcher)
    interleaving_store = _InterleavingStore(
        store, lambda: other.ingest(source, _ok(10, items=[_feedback(4, 11)]), _at(10)))
    report = _ingest_service(interleaving_store, dispatcher).ingest(
        source, _ok(5, items=[_feedback(50, 60)]), _at(5))
    assert report.result == "conflict"
    assert _stored_count(store) == 4 and store.get_attention_source_state("elum", "api").last_generated_at == _at(10)
    assert all("+47" not in notification.body for notification in dispatcher.notifications)


def test_push와_pull이_동시에_들어와도_가장_늦은_스냅샷이_남는다(store, ingest, source):
    ingest.ingest(source, _ok(0), _at(0))
    threads = [threading.Thread(target=ingest.ingest, args=(source, _ok(minutes, items=[_feedback(minutes, 100)]),
                                                             _at(20)))
               for minutes in (7, 3, 9, 1, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert _stored_count(store) == 9 and store.get_attention_source_state("elum", "api").last_generated_at == _at(9)


def test_실패해도_항목과_마지막_성공은_유지하고_실패만_기록한다(store, ingest, source):
    ingest.ingest(source, _ok(0), _at(0))
    ingest.ingest(source, FetchOutcome("timeout", None, None, "timeout"), _at(1))
    report = ingest.ingest(source, FetchOutcome("ok", {"schema": "other"}, None, None), _at(2))
    state = store.get_attention_source_state("elum", "api")
    assert report.result == "invalid" and state.last_result == "invalid" and state.last_error
    assert state.consecutive_failures == 2 and state.last_success_at == _at(0) and state.etag == '"v1"'
    assert _stored_count(store) == 3


def test_not_modified는_성공_시각만_갱신하고_항목을_유지한다(store, ingest, source):
    ingest.ingest(source, _ok(0), _at(0))
    ingest.ingest(source, FetchOutcome("error", None, None, "http_503"), _at(1))
    report = ingest.ingest(source, FetchOutcome("not_modified", None, '"v1"', None), _at(2))
    state = store.get_attention_source_state("elum", "api")
    assert report.result == "not_modified" and state.consecutive_failures == 0 and state.last_error is None
    assert state.last_success_at == _at(2) and state.last_generated_at == _at(0) and _stored_count(store) == 3


def test_연동_끊김은_한_번_알리고_다시_성공하면_복구를_한_번_알린다(store, dispatcher, ingest, source):
    ingest.ingest(source, _ok(0), _at(0))
    failure = FetchOutcome("unauthorized", None, None, "http_401")
    assert ingest.ingest(source, failure, _at(4)).notification_count == 0
    assert ingest.ingest(source, failure, _at(6)).notification_count == 1
    assert ingest.ingest(source, failure, _at(7)).notification_count == 0
    assert store.get_attention_source_state("elum", "api").failure_alerted_at == _at(6)
    disconnected = dispatcher.notifications[0]
    assert (disconnected.kind, disconnected.title) == ("error", "이룸 확인할 일 연동 끊김") and "http_401" in disconnected.body

    ingest.ingest(source, FetchOutcome("not_modified", None, None, None), _at(8))
    assert dispatcher.titles()[-1] == "이룸 확인할 일 연동 복구"
    assert store.get_attention_source_state("elum", "api").failure_alerted_at is None
    ingest.ingest(source, _ok(9), _at(9))
    assert len(dispatcher.notifications) == 2


def test_프로젝트_서비스가_down이면_연동_끊김_알림을_생략한다(store, dispatcher, source):
    ingest = _ingest_service(store, dispatcher, down_projects=("elum",))
    ingest.ingest(source, _ok(0), _at(0))
    ingest.ingest(source, FetchOutcome("error", None, None, "connection_error"), _at(10))
    assert dispatcher.notifications == []
    assert store.get_attention_source_state("elum", "api").failure_alerted_at is None


def test_push_전용_소스는_check_source_health로_끊김을_한_번만_알린다(store, dispatcher, ingest, source):
    ingest.check_source_health(source, _at(4))
    assert store.get_attention_source_state("elum", "api") is None
    ingest.check_source_health(source, _at(6))
    ingest.check_source_health(source, _at(9))
    assert dispatcher.titles() == ["이룸 확인할 일 연동 끊김"]
    assert store.get_attention_source_state("elum", "api").failure_alerted_at == _at(6)


def test_버린_항목은_보고에_남고_빠진_항목은_missing_since만_기록한다(store, ingest, source):
    budget = {"key": "budget.daily", "label": "오늘 AI 비용", "kind": "gauge", "value": 3, "level": "ok"}
    ingest.ingest(source, _ok(0, items=[_feedback(3, 10), budget]), _at(0))
    report = ingest.ingest(source, _ok(1, items=[budget, {"key": "BAD", "label": "x", "kind": "count",
                                                            "count": 1, "level": "info"}]), _at(1))
    assert report.dropped_items == (("#1", "invalid_key"),)
    items = store.load_attention_items("elum", "api")
    assert items["feedback.new"].missing_since == _at(1) and items["budget.daily"].missing_since is None


def test_발송이_실패해도_반영한_상태는_남는다(store, source):
    dispatcher = FakeDispatcher(failing_titles=(ITEM_TITLE,))
    ingest = _ingest_service(store, dispatcher)
    ingest.ingest(source, _ok(0), _at(0))
    report = ingest.ingest(source, _ok(1, items=[_feedback(6, 13)]), _at(1))
    assert report.result == "ok" and report.notification_count == 1 and _stored_count(store) == 6


def test_poll_after_seconds는_범위로_자르고_interval과_큰_값으로_다음_수집_시각을_정한다(store, ingest, source):
    ingest.ingest(source, _ok(0, poll_after_seconds=5), _at(0))
    assert store.get_attention_source_state("elum", "api").next_due_at == _at(1)
    ingest.ingest(source, _ok(1, poll_after_seconds=99999), _at(1))
    assert store.get_attention_source_state("elum", "api").next_due_at == _at(61)
    ingest.ingest(source, _ok(2), _at(2))
    assert store.get_attention_source_state("elum", "api").next_due_at is None


def test_preview는_DB와_발송을_바꾸지_않고_요약을_돌려준다(store, dispatcher, ingest, source):
    gauge = {"key": "budget.daily", "label": "오늘 AI 비용", "kind": "gauge", "value": 8.2, "limit": 10,
             "unit": "USD", "level": "warning"}
    body = ingest.preview(source, _ok(0, items=[_feedback(3, 182), gauge, {"key": "x"}]))
    assert body["result"] == "ok" and body["errors"] == [] and body["dropped_items"][0]["key"] == "#2"
    assert [item["summary"] for item in body["items"]] == ["3건 (전체 182)", "8.2 / 10 USD"]
    assert store.get_attention_source_state("elum", "api") is None and store.load_attention_items("elum", "api") == {}
    assert dispatcher.notifications == []

    invalid = ingest.preview(source, FetchOutcome("ok", {"schema": "other"}, None, None))
    assert invalid["result"] == "invalid" and invalid["error_label"] in invalid["errors"]
    failed = ingest.preview(source, FetchOutcome("unauthorized", None, None, "token_missing"))
    assert (failed["result"], failed["error_label"], failed["items"]) == ("unauthorized", "token_missing", [])


def test_generated_at이_5분_넘게_미래면_invalid로_기록하고_이후_스냅샷을_막지_않는다(store, ingest, source):
    ingest.ingest(source, _ok(0), _at(0))
    report = ingest.ingest(source, _ok(30, items=[_feedback(99, 99)]), _at(1))
    state = store.get_attention_source_state("elum", "api")
    assert (report.result, state.last_error, state.last_generated_at) == ("invalid", "future_generated_at", _at(0))
    assert ingest.ingest(source, _ok(2, items=[_feedback(4, 11)]), _at(2)).result == "ok"
    assert _stored_count(store) == 4
