"""관제소 저장소 동시성: 여러 스레드의 장애 열기·이벤트 기록, close 후 재사용, 다른 스레드 사용"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from service.control_tower.check_runner import CheckResult
from service.control_tower.state_machine import Observation
from service.control_tower.store import ControlTowerStore

SERVICE_ID = "elum-api"
BASE_TIME = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)  # KST 09:00
OK = Observation(CheckResult(True, False, 200, 120, None, BASE_TIME), None, False)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def test_여러_스레드의_동시_장애_열기는_하나만_만든다(store):
    opened_ids: list[int] = []
    errors: list[Exception] = []

    def open_in_thread():
        try:
            opened_ids.append(store.open_incident(SERVICE_ID, "service_down", BASE_TIME))
        except Exception as error:  # noqa: BLE001 테스트에서 스레드 예외 수집
            errors.append(error)

    threads = [threading.Thread(target=open_in_thread) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(set(opened_ids)) == 1


def test_여러_스레드의_동시_이벤트_기록은_하나만_True다(store):
    results: list[bool] = []

    def record_in_thread():
        results.append(store.record_event("elum", "error", "same-key", BASE_TIME))

    threads = [threading.Thread(target=record_in_thread) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1


def test_close_후에도_다시_사용할_수_있다(store):
    store.set_meta("key", "value")
    store.close()

    assert store.get_meta("key") == "value"


def test_다른_스레드에서도_같은_저장소를_쓸_수_있다(store):
    errors: list[Exception] = []

    def write_in_thread():
        try:
            store.set_meta("thread", "ok")
            store.save_results(SERVICE_ID, OK, BASE_TIME)
        except Exception as error:  # noqa: BLE001 테스트에서 스레드 예외 수집
            errors.append(error)

    worker_thread = threading.Thread(target=write_in_thread)
    worker_thread.start()
    worker_thread.join()

    assert errors == []
    assert store.get_meta("thread") == "ok"
