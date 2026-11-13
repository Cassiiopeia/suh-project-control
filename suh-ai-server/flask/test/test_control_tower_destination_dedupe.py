"""관제소 받을 곳 중복 발송 방지: 기본 발송 실패 재시도에도 1번, 기억 기간 후 다시, 다른 알림은 발송, 비밀값 없음 기록은 백그라운드"""
from __future__ import annotations

from datetime import timedelta

import pytest

from control_tower_destination_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    DISCORD_URL, NOW, SECRET_ENVIRON, FakeBindingStore, _add_destination, _notification, _results_by_id, _run_now,
    fast_kdf,
)
from control_tower_poller_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    CANARY_TARGET, FakeClock, check_runner, clock, make_poller, registry_path, run_ticks, store,
)
from service.control_tower import destination_delivery
from service.control_tower.destination_dedupe import DELIVERED_NOTIFICATION_MEMORY_WINDOW, DeliveredNotificationMemory
from service.control_tower.destination_delivery import DestinationDeliverer
from service.control_tower.event_dispatcher import EventDispatcher
from service.control_tower.registry_models import PROJECT_CHANNEL_KINDS


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


def test_dedupe_key가_없으면_제목과_서비스_목록으로_구분한다(store, apprise_sends):
    _add_destination(store, "elum", "report", DISCORD_URL)
    deliverer = DestinationDeliverer(store, _run_now, SECRET_ENVIRON, now_provider=lambda: NOW)

    deliverer.deliver(_notification())
    deliverer.deliver(_notification())
    deliverer.deliver(_notification(title="신고 접수 2"))

    assert [title for _url, title in apprise_sends] == ["신고 접수", "신고 접수 2"]


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
