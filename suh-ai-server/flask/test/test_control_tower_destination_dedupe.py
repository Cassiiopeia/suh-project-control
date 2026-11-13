"""관제소 받을 곳 중복 발송 방지: 재시도에도 1번, 기억 기간 후 다시, key 없음·앱 이벤트는 기억 안 함, 연동 전이마다 다른 key, 비밀값 없음 기록은 백그라운드"""
from __future__ import annotations

from datetime import timedelta

import pytest

from control_tower_destination_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    DISCORD_URL, NOW, SECRET_ENVIRON, FakeBindingStore, _add_destination, _notification, _results_by_id, _run_now,
    fast_kdf,
)
from control_tower_discord_fakes import ELUM, make_registry
from control_tower_poller_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    CANARY_TARGET, FakeClock, FakeDispatcher, check_runner, clock, make_poller, registry_path, run_ticks, store,
)
from service.control_tower import destination_delivery
from service.control_tower.app_attention_fetch import FetchOutcome
from service.control_tower.app_attention_ingest import AppAttentionIngest
from service.control_tower.app_attention_store import AttentionSource
from service.control_tower.destination_dedupe import DELIVERED_NOTIFICATION_MEMORY_WINDOW, DeliveredNotificationMemory
from service.control_tower.destination_delivery import DestinationDeliverer
from service.control_tower.event_dispatcher import EventDispatcher
from service.control_tower.registry_models import PROJECT_CHANNEL_KINDS
from service.control_tower.store import EVENT_DEDUPE_WINDOW


class FailingDiscordClient:
    """디스코드 장애: 전송 시도 기록 > 항상 실패"""

    def __init__(self):
        self.attempt_count = 0

    def send_embed(self, channel_id, embed):
        self.attempt_count += 1
        return False


@pytest.fixture
def apprise_sends(monkeypatch):
    sends = []
    monkeypatch.setattr(destination_delivery, "_send_with_apprise",
                        lambda url, title, body: sends.append((url, title)) or True)
    return sends


def test_디스코드_실패로_폴러가_같은_알림을_다시_보내도_받을_곳에는_1번(
        registry_path, store, check_runner, clock, apprise_sends):
    for kind in PROJECT_CHANNEL_KINDS:
        _add_destination(store, "elum", kind, DISCORD_URL)
    discord_client = FailingDiscordClient()
    dispatcher = EventDispatcher(FakeBindingStore(), lambda: discord_client, "https://status.example.com",
                                 destination_deliverer=DestinationDeliverer(store, _run_now, SECRET_ENVIRON,
                                                                            now_provider=clock))
    check_runner.is_ok_by_target[CANARY_TARGET] = False

    run_ticks(make_poller(registry_path, store, dispatcher, check_runner, clock), clock, 6)

    assert discord_client.attempt_count >= 2
    assert len(apprise_sends) == 1


def test_같은_dedupe_key도_기억_기간이_지나면_다시_보낸다(store, apprise_sends):
    _add_destination(store, "elum", "report", DISCORD_URL)
    clock = FakeClock(NOW)
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=clock)

    deliverer.deliver(_notification(dedupe_key="report:1"))
    deliverer.deliver(_notification(dedupe_key="report:1"))
    clock.moment = NOW + DELIVERED_NOTIFICATION_MEMORY_WINDOW
    deliverer.deliver(_notification(dedupe_key="report:1"))

    assert len(apprise_sends) == 2


def test_dedupe_key가_다르면_보낸다(store, apprise_sends):
    _add_destination(store, "elum", "report", DISCORD_URL)
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=lambda: NOW)

    deliverer.deliver(_notification(dedupe_key="report:1"))
    deliverer.deliver(_notification(dedupe_key="report:2"))

    assert len(apprise_sends) == 2


def test_dedupe_key가_없으면_기억하지_않고_매번_보낸다(store, apprise_sends):
    _add_destination(store, "elum", "report", DISCORD_URL)
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=lambda: NOW)

    deliverer.deliver(_notification())
    deliverer.deliver(_notification())

    assert len(apprise_sends) == 2


# ---- 앱 이벤트: event_log 중복 억제만 적용 (받을 곳 기억 우회) ----

def _event_dispatcher(store, clock) -> EventDispatcher:
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=clock)
    return EventDispatcher(store, lambda: None, "https://status.example.com", destination_deliverer=deliverer)


def _event(**overrides) -> dict:
    return {"kind": "report", "severity": "warning", "title": "신고 접수", **overrides}


def test_같은_제목_다른_본문_앱_이벤트는_둘_다_받을_곳에_간다(store, apprise_sends):
    _add_destination(store, "elum", "report", DISCORD_URL)
    dispatcher = _event_dispatcher(store, FakeClock(NOW))

    dispatcher.accept_event("elum", _event(body="신고 1번"), NOW)
    dispatcher.accept_event("elum", _event(body="신고 2번"), NOW + timedelta(seconds=1))

    assert len(apprise_sends) == 2


def test_같은_dedupe_key_앱_이벤트도_event_log가_받으면_다시_간다(store, apprise_sends):
    _add_destination(store, "elum", "report", DISCORD_URL)
    clock = FakeClock(NOW)
    dispatcher = _event_dispatcher(store, clock)

    dispatcher.accept_event("elum", _event(dedupe_key="report-1"), NOW)
    dispatcher.accept_event("elum", _event(dedupe_key="report-1"), NOW + timedelta(minutes=1))
    clock.moment = NOW + EVENT_DEDUPE_WINDOW + timedelta(seconds=1)
    dispatcher.accept_event("elum", _event(dedupe_key="report-1"), clock.moment)

    assert len(apprise_sends) == 2


# ---- 확인할 일 연동 끊김·복구: 전이마다 다른 key ----

def _attention_ingest(store, dispatcher) -> AppAttentionIngest:
    registry = make_registry(ELUM)
    return AppAttentionIngest(store, dispatcher, lambda: registry, lambda project_id: False)


def _attention_source(store) -> AttentionSource:
    attention_source = AttentionSource("elum", "api", "https://elum.example/attention", True, "both", 60, 5, 300,
                                       NOW, NOW)
    store.save_attention_source(attention_source)
    return attention_source


def _attention_snapshot(minutes: int) -> FetchOutcome:
    document = {"schema": "attention", "version": "1.0",
                "source": {"app": "elum-server", "app_version": "2.3.1", "environment": "production"},
                "generated_at": (NOW + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"), "items": []}
    return FetchOutcome("ok", document, None, None)


def _run_attention_outages(store, dispatcher) -> None:
    """성공 > 끊김 > 복구 > 끊김 > 복구 (stale 5분, 24시간 안)"""
    ingest, source = _attention_ingest(store, dispatcher), _attention_source(store)
    failure, not_modified = FetchOutcome("unauthorized", None, None, "http_401"), FetchOutcome("not_modified", None,
                                                                                                None, None)
    ingest.ingest(source, _attention_snapshot(0), NOW)
    for minutes, outcome in ((6, failure), (8, not_modified), (9, failure), (14, failure), (15, not_modified)):
        ingest.ingest(source, outcome, NOW + timedelta(minutes=minutes))


def test_24시간_안_끊김_복구_반복은_받을_곳에_4번_간다(store, apprise_sends):
    _add_destination(store, "elum", "error", DISCORD_URL)
    recording_dispatcher = FakeDispatcher()
    _run_attention_outages(store, recording_dispatcher)
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=lambda: NOW)

    for notification in recording_dispatcher.notifications:
        deliverer.deliver(notification)

    assert len(recording_dispatcher.notifications) == 4
    assert len(apprise_sends) == 4


def test_연동_끊김_재시도는_같은_key라_받을_곳에_1번(store, apprise_sends):
    _add_destination(store, "elum", "error", DISCORD_URL)
    flaky_dispatcher = FakeDispatcher(undelivered_counts={"이룸 확인할 일 연동 끊김": 1})
    ingest, source = _attention_ingest(store, flaky_dispatcher), _attention_source(store)
    failure = FetchOutcome("unauthorized", None, None, "http_401")
    ingest.ingest(source, _attention_snapshot(0), NOW)
    ingest.ingest(source, failure, NOW + timedelta(minutes=6))
    ingest.ingest(source, failure, NOW + timedelta(minutes=7))
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=lambda: NOW)

    for notification in flaky_dispatcher.notifications:
        deliverer.deliver(notification)

    assert flaky_dispatcher.titles() == ["이룸 확인할 일 연동 끊김"] * 2
    assert len(apprise_sends) == 1


def test_기억_항목_수는_상한을_넘지_않고_오래된_것부터_잊는다():
    memory = DeliveredNotificationMemory(window=timedelta(days=1), max_entries=2)
    first, second, third = (_notification(dedupe_key=f"report:{index}") for index in range(3))

    assert [memory.remember_if_new(item, NOW) for item in (first, second, third)] == [True, True, True]
    assert memory.remember_if_new(third, NOW) is False
    assert memory.remember_if_new(first, NOW) is True


def test_비밀값_없음_기록은_요청_스레드가_아닌_백그라운드_1건에서(store, apprise_sends):
    destination_id = _add_destination(store, "elum", "report", DISCORD_URL)
    _add_destination(store, "elum", "report", "discord://222/second-token")
    queued_tasks = []
    deliverer = DestinationDeliverer(store, lambda task, thread_name: queued_tasks.append(task), {})

    deliverer.deliver(_notification())

    assert len(queued_tasks) == 1
    assert _results_by_id(store)[destination_id] is None
    queued_tasks[0]()
    assert set(_results_by_id(store).values()) == {destination_delivery.RESULT_SECRET_MISSING}
    assert apprise_sends == []
