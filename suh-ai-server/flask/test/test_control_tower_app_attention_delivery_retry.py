"""앱 확인할 일 발송 실패 재시도: 못 보낸 항목 알림·연동 끊김/복구는 기준을 되돌려 다음 처리에서 다시 보냄
디스코드 미설정이면 되돌리지 않음, 채널 알림이 전달됐으면 전역 긴급만 실패해도 다시 보내지 않음"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from service.control_tower.alert_planner import GLOBAL_SCOPE
from service.control_tower.app_attention_fetch import FetchOutcome
from service.control_tower.app_attention_ingest import AppAttentionIngest
from service.control_tower.app_attention_store import AttentionSource
from service.control_tower.store import ControlTowerStore
from control_tower_discord_fakes import ELUM, make_registry
from control_tower_poller_fixtures import FakeDispatcher

BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
ITEM_TITLE = "이룸 확인할 일"
DISCONNECTED_TITLE = "이룸 확인할 일 연동 끊김"
RECOVERED_TITLE = "이룸 확인할 일 연동 복구"


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


@pytest.fixture
def source(store) -> AttentionSource:
    attention_source = AttentionSource("elum", "api", "https://elum.example/attention", True, "both", 60, 5, 300,
                                       BASE_TIME, BASE_TIME)
    store.save_attention_source(attention_source)
    return attention_source


class _GlobalFailingDispatcher(FakeDispatcher):
    """전역 긴급 채널만 전달 실패"""

    def dispatch(self, notification) -> bool:
        self.notifications.append(notification)
        return notification.scope != GLOBAL_SCOPE


def _ingest_service(store, dispatcher) -> AppAttentionIngest:
    registry = make_registry(ELUM)
    return AppAttentionIngest(store, dispatcher, lambda: registry, lambda project_id: False)


def _at(minutes: float) -> datetime:
    return BASE_TIME + timedelta(minutes=minutes)


def _ok(minutes: int, items: list[dict]) -> FetchOutcome:
    document = {"schema": "attention", "version": "1.0",
                "source": {"app": "elum-server", "environment": "production"},
                "generated_at": _at(minutes).isoformat().replace("+00:00", "Z"), "items": items}
    return FetchOutcome("ok", document, None, None)


def _feedback(count: int, total: int) -> dict:
    return {"key": "feedback.new", "label": "새 의견", "kind": "count", "count": count, "total": total,
            "level": "info"}


def _batch(state: str, level: str) -> dict:
    return {"key": "batch.status", "label": "배치", "kind": "state", "state": state, "level": level}


def _budget(value: float, level: str) -> dict:
    return {"key": "budget.daily", "label": "비용", "kind": "gauge", "value": value, "limit": 10, "level": level}


def _alert_state(store, key: str):
    return store.load_attention_alert_states("elum", "api")[key]


def _item_bodies(dispatcher) -> list[str]:
    return [notification.body for notification in dispatcher.notifications if notification.title == ITEM_TITLE]


@pytest.mark.parametrize("dispatcher", [FakeDispatcher(undelivered_counts={ITEM_TITLE: 1}),
                                        FakeDispatcher(failing_titles=(ITEM_TITLE,))],
                         ids=["not_delivered", "exception"])
def test_new_알림을_못_보내면_증가분을_쌓아_두고_다음_처리에서_합쳐_보낸다(store, source, dispatcher):
    ingest = _ingest_service(store, dispatcher)
    ingest.ingest(source, _ok(0, [_feedback(3, 10)]), _at(0))
    ingest.ingest(source, _ok(1, [_feedback(5, 12)]), _at(1))
    held = _alert_state(store, "feedback.new")
    assert (held.pending_new_count, held.last_alerted_at, held.last_alerted_total) == (2, None, 12)

    dispatcher.failing_titles = ()
    ingest.ingest(source, _ok(2, [_feedback(6, 13)]), _at(2))
    assert "+3, 지금 6건" in _item_bodies(dispatcher)[-1]
    sent = _alert_state(store, "feedback.new")
    assert (sent.pending_new_count, sent.last_alerted_at) == (0, _at(2))


def test_state_threshold_알림을_못_보내면_처리_전_기준을_유지해_같은_줄을_다시_보낸다(store, source):
    dispatcher = FakeDispatcher(undelivered_counts={ITEM_TITLE: 1})
    ingest = _ingest_service(store, dispatcher)
    ingest.ingest(source, _ok(0, [_batch("ok", "ok"), _budget(3, "ok")]), _at(0))
    ingest.ingest(source, _ok(1, [_batch("down", "warning"), _budget(12, "warning")]), _at(1))
    assert _alert_state(store, "batch.status").last_alerted_state == "ok"
    assert _alert_state(store, "budget.daily").is_threshold_exceeded is False

    ingest.ingest(source, _ok(2, [_batch("down", "warning"), _budget(12, "warning")]), _at(2))
    retried_body = _item_bodies(dispatcher)[-1]
    assert "상태 ok > down" in retried_body and "기준 10 넘음" in retried_body
    assert _alert_state(store, "batch.status").last_alerted_state == "down"
    ingest.ingest(source, _ok(3, [_batch("down", "warning"), _budget(12, "warning")]), _at(3))
    assert len(_item_bodies(dispatcher)) == 2


def test_디스코드가_설정되지_않으면_기준을_되돌리지_않는다(store, source):
    dispatcher = FakeDispatcher(is_configured=False)
    ingest = _ingest_service(store, dispatcher)
    ingest.ingest(source, _ok(0, [_feedback(3, 10)]), _at(0))
    ingest.ingest(source, _ok(1, [_feedback(5, 12)]), _at(1))
    alert_state = _alert_state(store, "feedback.new")
    assert (alert_state.pending_new_count, alert_state.last_alerted_at) == (0, _at(1))


def test_채널_알림이_전달되면_전역_긴급만_실패해도_다시_보내지_않는다(store, source):
    dispatcher = _GlobalFailingDispatcher()
    ingest = _ingest_service(store, dispatcher)
    ingest.ingest(source, _ok(0, [_batch("ok", "ok")]), _at(0))
    ingest.ingest(source, _ok(1, [_batch("down", "critical")]), _at(1))
    ingest.ingest(source, _ok(2, [_batch("down", "critical")]), _at(2))
    assert [notification.scope for notification in dispatcher.notifications] == ["elum", GLOBAL_SCOPE]


def test_연동_끊김_복구를_못_보내면_끊김_알림_시각을_되돌려_다음_처리에서_다시_보낸다(store, source):
    dispatcher = FakeDispatcher(undelivered_counts={DISCONNECTED_TITLE: 1, RECOVERED_TITLE: 1})
    ingest = _ingest_service(store, dispatcher)
    ingest.ingest(source, _ok(0, [_feedback(3, 10)]), _at(0))
    failure = FetchOutcome("error", None, None, "http_503")
    ingest.ingest(source, failure, _at(6))
    assert store.get_attention_source_state("elum", "api").failure_alerted_at is None
    ingest.ingest(source, failure, _at(7))
    assert store.get_attention_source_state("elum", "api").failure_alerted_at == _at(7)

    ingest.ingest(source, _ok(8, [_feedback(3, 10)]), _at(8))
    assert store.get_attention_source_state("elum", "api").failure_alerted_at == _at(7)
    ingest.ingest(source, FetchOutcome("not_modified", None, None, None), _at(9))
    assert store.get_attention_source_state("elum", "api").failure_alerted_at is None
    assert dispatcher.titles() == [DISCONNECTED_TITLE, DISCONNECTED_TITLE, RECOVERED_TITLE, RECOVERED_TITLE]


def test_push_전용_연동_끊김도_못_보내면_다음_틱에_다시_보낸다(store, source):
    dispatcher = FakeDispatcher(undelivered_counts={DISCONNECTED_TITLE: 1})
    ingest = _ingest_service(store, dispatcher)
    ingest.check_source_health(source, _at(6))
    assert store.get_attention_source_state("elum", "api").failure_alerted_at is None
    ingest.check_source_health(source, _at(7))
    ingest.check_source_health(source, _at(8))
    assert dispatcher.titles() == [DISCONNECTED_TITLE, DISCONNECTED_TITLE]
    assert store.get_attention_source_state("elum", "api").failure_alerted_at == _at(7)
