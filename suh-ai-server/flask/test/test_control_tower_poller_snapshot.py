"""관제소 폴러 snapshot(): 등록 정보·상태·서비스별 마지막 관측·마지막 틱 시각, 불변 뷰, 외부 결과 이월"""
from __future__ import annotations

import pytest

from control_tower_poller_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    BASE_TIME, NAS_TARGET, FakeHeartbeatClient, check_runner, clock, dispatcher, make_poller, registry_path,
    run_ticks, store,
)
from service.control_tower.check_runner import CheckResult
from service.control_tower.heartbeat_client import HeartbeatResponse


def _external_ok(checked_at) -> CheckResult:
    return CheckResult(True, False, 200, 40, None, checked_at)


def test_틱_전에는_등록_정보와_관측이_비어_있다(registry_path, store, dispatcher, check_runner, clock):
    snapshot = make_poller(registry_path, store, dispatcher, check_runner, clock).snapshot()

    assert snapshot.registry is None
    assert dict(snapshot.states) == {} and dict(snapshot.observations) == {}
    assert snapshot.last_tick_at is None


def test_틱_후에는_서비스별_마지막_내부_관측과_상태와_틱_시각이_담긴다(
        registry_path, store, dispatcher, check_runner, clock):
    check_runner.is_ok_by_target[NAS_TARGET] = False
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock)

    poller.tick()
    snapshot = poller.snapshot()

    assert snapshot.registry is not None and snapshot.last_tick_at == BASE_TIME
    assert snapshot.observations["nas"].internal.is_ok is False
    assert snapshot.observations["nas"].internal.error == "connection_error"
    assert snapshot.states["nas"].consecutive_failures == 1


def test_snapshot의_관측과_상태는_수정할_수_없다(registry_path, store, dispatcher, check_runner, clock):
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock)
    poller.tick()
    snapshot = poller.snapshot()

    with pytest.raises(TypeError):
        snapshot.observations["nas"] = None
    with pytest.raises(TypeError):
        snapshot.states["nas"] = None


def test_이전_snapshot은_다음_틱_후에도_바뀌지_않는다(registry_path, store, dispatcher, check_runner, clock):
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock)
    poller.tick()
    first_snapshot = poller.snapshot()
    clock.advance()
    poller.tick()

    assert first_snapshot.last_tick_at == BASE_TIME
    assert poller.snapshot().last_tick_at == clock.moment


def test_외부_결과가_없는_틱에서도_3분_안의_마지막_외부_결과는_유지된다(
        registry_path, store, dispatcher, check_runner, clock):
    responses = [lambda now: HeartbeatResponse({"elum-api": _external_ok(now)}, now),
                 lambda now: HeartbeatResponse({}, now)]
    heartbeat = FakeHeartbeatClient(lambda now: responses[min(len(heartbeat.calls) - 1, 1)](now))
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat)

    run_ticks(poller, clock, 2)
    observation = poller.snapshot().observations["elum-api"]

    assert observation.external is not None and observation.external.is_ok is True
    assert observation.is_external_known is True


def test_3분_넘은_마지막_외부_결과는_버린다(registry_path, store, dispatcher, check_runner, clock):
    heartbeat = FakeHeartbeatClient(lambda now: (
        HeartbeatResponse({"elum-api": _external_ok(now)}, now) if len(heartbeat.calls) == 1 else None))
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat)

    poller.tick()
    clock.advance(4)
    poller.tick()

    observation = poller.snapshot().observations["elum-api"]
    assert observation.external is None and observation.is_external_known is False
