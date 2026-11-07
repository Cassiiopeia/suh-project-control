"""관제소 다수 장애·복구 묶음 (R29): 기준 이상 개별 down·복구 > 전역 긴급 1건, 미만은 개별, 재알림 제외, 발송 실패 재시도"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from control_tower_alert_fixtures import BASE_TIME, DOWN_SINCE, down_state, recovery_transition, titles, up_state
from control_tower_poller_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    FakeDispatcher, FakeHeartbeatClient, check_runner, clock, make_poller, run_ticks, store,
)
from service.control_tower.alert_planner import plan_notifications
from service.control_tower.alert_texts import BULK_NAME_LIMIT
from service.control_tower.check_runner import CheckResult
from service.control_tower.heartbeat_client import HeartbeatResponse
from service.control_tower.registry import AlertPolicy, ProjectSpec, Registry, ServiceSpec


def _external_only_registry(service_count: int, alert: AlertPolicy = AlertPolicy()) -> Registry:
    """외부 점검만 있는 프로젝트 서비스 N개 (부모 없음)"""
    services = tuple(ServiceSpec(f"site-{index:02d}", f"사이트 {index:02d}", "sites") for index in range(service_count))
    return Registry(projects=(ProjectSpec("sites", "사이트"),), services=services, alert=alert)


def _plan(registry: Registry, states, transitions=()):
    return plan_notifications(registry, states, list(transitions), {}, BASE_TIME)


def _all_down(registry: Registry, **state_options):
    return {service.id: down_state(cause="unreachable", **state_options) for service in registry.services}


# ---------- 계획 ----------

def test_기준_이상_첫_down은_전역_긴급_1건으로_묶고_각_서비스를_알림_완료로_기록한다():
    registry = _external_only_registry(32)

    notifications, new_states = _plan(registry, _all_down(registry))

    assert len(notifications) == 1
    bulk = notifications[0]
    assert (bulk.scope, bulk.kind, bulk.severity) == ("global", "alert", "critical")
    assert bulk.title == "[다수 장애] 32개 서비스"
    assert bulk.dedupe_key == f"bulk-down:{BASE_TIME.isoformat()}"
    assert bulk.service_ids == tuple(service.id for service in registry.services)
    body_lines = bulk.body.splitlines()
    assert len(body_lines) == 32 and body_lines[0] == "사이트 00 (접속 불가)"
    assert all(state.is_down_notified and state.last_notified_at == BASE_TIME for state in new_states.values())


def test_기준_미만_첫_down은_개별로_보낸다():
    registry = _external_only_registry(4)

    notifications, _ = _plan(registry, _all_down(registry))

    assert titles(notifications) == [f"[다운] 사이트 {index:02d}" for index in range(4)]
    assert {notification.scope for notification in notifications} == {"sites"}


def test_묶음_본문은_40개까지_나열하고_나머지는_개수만_적는다():
    registry = _external_only_registry(BULK_NAME_LIMIT + 5)

    notifications, _ = _plan(registry, _all_down(registry))

    body_lines = notifications[0].body.splitlines()
    assert len(body_lines) == BULK_NAME_LIMIT + 1 and body_lines[-1] == "외 5개"
    assert len(notifications[0].service_ids) == BULK_NAME_LIMIT + 5


def test_재알림은_세지_않고_그대로_보낸다():
    registry = _external_only_registry(7)
    states = _all_down(registry)
    reminder_due = BASE_TIME - timedelta(hours=6, minutes=1)
    for service in registry.services[:3]:
        states[service.id] = down_state(cause="unreachable", is_down_notified=True, last_notified_at=reminder_due,
                                        since=DOWN_SINCE - timedelta(hours=7))

    notifications, _ = _plan(registry, states)

    assert titles(notifications) == [f"[계속 다운] 사이트 {index:02d}" for index in range(3)] \
        + [f"[다운] 사이트 {index:02d}" for index in range(3, 7)]


def test_묶음_기준은_등록_파일_alert_값을_따른다():
    registry = _external_only_registry(2, AlertPolicy(bulk_alert_threshold=2))

    notifications, _ = _plan(registry, _all_down(registry))

    assert titles(notifications) == ["[다수 장애] 2개 서비스"]


def test_기준_이상_복구는_다수_복구_1건이다():
    registry = _external_only_registry(5)
    notified_up = replace(up_state(since=BASE_TIME), last_notified_at=BASE_TIME - timedelta(minutes=1))
    states = {service.id: notified_up for service in registry.services}
    transitions = [recovery_transition(service.id, since=BASE_TIME - timedelta(minutes=2), cause="unreachable")
                   for service in registry.services]

    notifications, new_states = _plan(registry, states, transitions)

    assert len(notifications) == 1
    bulk = notifications[0]
    assert (bulk.scope, bulk.kind, bulk.severity, bulk.title) == ("global", "alert", "recovered", "[다수 복구] 5개 서비스")
    assert bulk.body.splitlines() == [service.name for service in registry.services]
    assert bulk.dedupe_key == f"bulk-recovered:{BASE_TIME.isoformat()}"
    assert all(state.last_notified_at == BASE_TIME for state in new_states.values())


# ---------- 폴러 ----------

def _write_external_only_registry(tmp_path, service_count: int):
    service_lines = "".join(
        f"""
      - id: site-{index:02d}
        name: 사이트 {index:02d}
        checks:
          external: {{url: "https://site{index:02d}.example.com/"}}"""
        for index in range(service_count))
    path = tmp_path / "services.yml"
    path.write_text("infrastructure:\n  - {id: home-network, name: 집 인터넷}\n"
                    "projects:\n  - id: sites\n    name: 사이트\n    services:" + service_lines + "\n", encoding="utf-8")
    return path


def _all_external_failing(service_count: int) -> FakeHeartbeatClient:
    """심박 성공 + 매 틱 새 checked_at의 외부 실패 N개 (들어오는 경로 장애)"""
    def factory(now):
        failure = CheckResult(False, False, None, 0, "connection_error", now)
        return HeartbeatResponse({f"site-{index:02d}": failure for index in range(service_count)}, now)
    return FakeHeartbeatClient(factory)


def test_외부_전용_32개가_함께_끊기면_알림은_정확히_1건이다(tmp_path, store, check_runner, clock):
    dispatcher = FakeDispatcher()
    poller = make_poller(_write_external_only_registry(tmp_path, 32), store, dispatcher, check_runner, clock,
                         _all_external_failing(32))

    run_ticks(poller, clock, 6)

    assert dispatcher.titles() == ["[다수 장애] 32개 서비스"]
    assert all(state.is_down_notified for service_id, state in store.load_states().items()
               if service_id.startswith("site-"))


def test_다수_장애_발송_실패는_다음_틱에_다시_보낸다(tmp_path, store, check_runner, clock):
    bulk_title = "[다수 장애] 5개 서비스"
    flaky_dispatcher = FakeDispatcher(undelivered_counts={bulk_title: 1})
    poller = make_poller(_write_external_only_registry(tmp_path, 5), store, flaky_dispatcher, check_runner, clock,
                         _all_external_failing(5))

    run_ticks(poller, clock, 6)

    assert flaky_dispatcher.titles() == [bulk_title, bulk_title]
    assert all(state.is_down_notified for service_id, state in store.load_states().items()
               if service_id.startswith("site-"))
