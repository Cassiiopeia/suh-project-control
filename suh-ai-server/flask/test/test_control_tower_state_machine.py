"""관제소 상태 기계: 연속 실패·성공 전이, 원인 판정, 외부 결과 미확인 무시, degraded, 최초 전이"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from service.control_tower.check_runner import CheckResult
from service.control_tower.registry import AlertPolicy
from service.control_tower.state_machine import INITIAL_STATE, Observation, ServiceState, advance

SERVICE_ID = "elum-api"
POLICY = AlertPolicy()
BASE_TIME = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)


def _result(is_ok: bool = True, is_slow: bool = False) -> CheckResult:
    return CheckResult(is_ok, is_slow, 200 if is_ok else None, 100, None if is_ok else "timeout", BASE_TIME)


OK = Observation(_result(), None, False)
FAIL = Observation(_result(False), None, False)
SLOW = Observation(_result(is_slow=True), None, False)
EXTERNAL_ONLY_FAIL = Observation(None, _result(False), True)
INTERNAL_OK_EXTERNAL_FAIL = Observation(_result(), _result(False), True)
BOTH_FAIL = Observation(_result(False), _result(False), True)


def _tick_time(tick_index: int) -> datetime:
    return BASE_TIME + timedelta(minutes=tick_index)


def _run(observations, start: ServiceState = INITIAL_STATE):
    """관측 열 순차 적용 > (최종 상태, 전이 목록)"""
    state, transitions = start, []
    for tick_index, observation in enumerate(observations):
        state, transition = advance(SERVICE_ID, state, observation, POLICY, _tick_time(tick_index))
        transitions.append(transition)
    return state, transitions


def _up_state() -> ServiceState:
    return replace(INITIAL_STATE, status="up", since=BASE_TIME)


def test_three_consecutive_failures_go_down_with_since_at_first_failure():
    state, transitions = _run([FAIL, FAIL, FAIL], _up_state())
    assert state.status == "down"
    assert state.since == _tick_time(0)
    assert transitions[:2] == [None, None]
    assert (transitions[2].before, transitions[2].after) == ("up", "down")
    assert transitions[2].since == _tick_time(0)
    assert transitions[2].service_id == SERVICE_ID


def test_two_failures_then_success_stays_up():
    state, transitions = _run([FAIL, FAIL, OK], _up_state())
    assert state.status == "up"
    assert state.consecutive_failures == 0
    assert transitions == [None, None, None]


def test_two_successes_needed_to_recover():
    down_state, _ = _run([FAIL, FAIL, FAIL], _up_state())
    state, transitions = _run([OK], down_state)
    assert state.status == "down"
    assert transitions == [None]
    state, transitions = _run([OK, OK], down_state)
    assert state.status == "up"
    assert (transitions[1].before, transitions[1].after) == ("down", "up")
    assert transitions[1].since == down_state.since


def test_cause_external_path_when_internal_ok_external_fails():
    state, transitions = _run([INTERNAL_OK_EXTERNAL_FAIL] * 3, _up_state())
    assert state.cause == "external_path"
    assert transitions[2].cause == "external_path"


def test_cause_service_down_when_both_fail():
    state, transitions = _run([BOTH_FAIL] * 3, _up_state())
    assert state.cause == "service_down"
    assert transitions[2].cause == "service_down"


def test_cause_unreachable_when_only_external_configured_and_fails():
    state, transitions = _run([EXTERNAL_ONLY_FAIL] * 3, _up_state())
    assert state.cause == "unreachable"
    assert transitions[2].cause == "unreachable"


def test_unknown_external_is_ignored_not_failure():
    observation = Observation(_result(), _result(False), False)
    state, transitions = _run([observation] * 5, _up_state())
    assert state.status == "up"
    assert state.consecutive_failures == 0
    assert transitions == [None] * 5


def test_no_data_tick_keeps_state_untouched():
    previous = replace(_up_state(), consecutive_failures=2)
    state, transition = advance(SERVICE_ID, previous, Observation(None, None, False), POLICY, _tick_time(0))
    assert state == previous and transition is None


def test_slow_but_ok_is_degraded_and_back_to_up():
    state, transitions = _run([SLOW, OK], _up_state())
    assert (transitions[0].before, transitions[0].after) == ("up", "degraded")
    assert (transitions[1].before, transitions[1].after) == ("degraded", "up")
    assert state.status == "up"


def test_failures_while_degraded_go_down():
    degraded_state, _ = _run([SLOW], _up_state())
    state, transitions = _run([FAIL] * 3, degraded_state)
    assert (transitions[2].before, transitions[2].after) == ("degraded", "down")


def test_unknown_initial_to_up_emits_no_transition():
    state, transition = advance(SERVICE_ID, INITIAL_STATE, OK, POLICY, BASE_TIME)
    assert state.status == "up"
    assert transition is None


def test_unknown_initial_to_down_is_a_transition():
    state, transitions = _run([FAIL] * 3)
    assert (transitions[2].before, transitions[2].after) == ("unknown", "down")


def test_leaving_down_resets_notified_flag_and_keeps_planner_fields():
    down_state = replace(_run([FAIL] * 3, _up_state())[0], is_down_notified=True, last_notified_at=BASE_TIME)
    still_down, _ = _run([OK], down_state)
    assert still_down.is_down_notified and still_down.last_notified_at == BASE_TIME
    recovered, _ = _run([OK, OK], down_state)
    assert recovered.is_down_notified is False and recovered.last_notified_at == BASE_TIME


def test_failure_streak_reset_by_success_restarts_since():
    state, _ = _run([FAIL, OK, FAIL], _up_state())
    assert state.consecutive_failures == 1
    assert state.since == _tick_time(2)


INTERNAL_OK_EXTERNAL_UNKNOWN = Observation(_result(), None, False)
INTERNAL_OK_EXTERNAL_OK = Observation(_result(), _result(), True)
EXTERNAL_ONLY_OK = Observation(None, _result(), True)


def test_external_cause_down_ignores_ticks_without_known_external_result():
    down_state, _ = _run([INTERNAL_OK_EXTERNAL_FAIL] * 3, _up_state())
    state, transitions = _run([INTERNAL_OK_EXTERNAL_UNKNOWN] * 3, down_state)
    assert state == down_state
    assert transitions == [None] * 3
    state, transitions = _run([INTERNAL_OK_EXTERNAL_OK] * 2, down_state)
    assert state.status == "up"
    assert (transitions[1].before, transitions[1].after) == ("down", "up")


def test_unreachable_down_recovers_only_with_known_external_successes():
    down_state, _ = _run([EXTERNAL_ONLY_FAIL] * 3, _up_state())
    state, _ = _run([Observation(None, None, False)] * 3, down_state)
    assert state == down_state
    state, transitions = _run([EXTERNAL_ONLY_OK] * 2, down_state)
    assert state.status == "up" and transitions[1] is not None


def test_service_down_cause_recovers_on_internal_ok_with_unknown_external():
    down_state, _ = _run([BOTH_FAIL] * 3, _up_state())
    state, transitions = _run([INTERNAL_OK_EXTERNAL_UNKNOWN] * 2, down_state)
    assert state.status == "up"
    assert transitions[1] is not None


def test_custom_policy_failures_to_down_two():
    policy = AlertPolicy(failures_to_down=2)
    state, first = advance(SERVICE_ID, _up_state(), FAIL, policy, _tick_time(0))
    state, second = advance(SERVICE_ID, state, FAIL, policy, _tick_time(1))
    assert first is None
    assert (second.before, second.after) == ("up", "down")
    assert second.since == _tick_time(0)


def test_failure_between_successes_requires_two_fresh_successes():
    down_state, _ = _run([FAIL] * 3, _up_state())
    state, transitions = _run([OK, FAIL, OK], down_state)
    assert state.status == "down"
    assert transitions == [None] * 3
    state, transition = advance(SERVICE_ID, state, OK, POLICY, _tick_time(10))
    assert state.status == "up"
    assert transition is not None
