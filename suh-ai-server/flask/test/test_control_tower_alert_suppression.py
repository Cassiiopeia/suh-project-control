"""관제소 알림 억제: 부모 묶음, 조상 사슬, 비활성 조상 건너뜀, 실패 연속 보류, 복구 유예 후 묶음, 집 인터넷"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from control_tower_alert_fixtures import (
    BASE_TIME, DOWN_SINCE, GRACE, REGISTRY, all_up, down_state, down_transition, plan, recovery_transition, titles,
    up_state,
)
from service.control_tower.check_runner import CheckResult
from service.control_tower.registry import ProjectSpec, Registry, ServiceSpec
from service.control_tower.state_machine import INITIAL_STATE, Observation, advance

NAS_RECOVERED_AT = BASE_TIME + timedelta(minutes=30)
NAS_NOTIFIED_AT = DOWN_SINCE + timedelta(minutes=3)


def _chain_registry(docker_host_status: str = "active") -> Registry:
    """nas > 도커 호스트(인프라) > 앱 3단 사슬"""
    return Registry(
        projects=(ProjectSpec("elum", "이룸"),),
        services=(ServiceSpec("app", "앱", "elum", depends_on="docker-host"),),
        infrastructure=(ServiceSpec("nas", "시놀로지 NAS", None),
                        ServiceSpec("docker-host", "도커 호스트", None, status=docker_host_status, depends_on="nas")),
    )


def _nas_just_recovered(**overrides):
    """NAS 복구 알림 직후 (계획기가 복구 알림 시 last_notified_at = 복구 시각 기록)"""
    return all_up(nas=up_state(since=NAS_RECOVERED_AT, last_notified_at=NAS_RECOVERED_AT), **overrides)


# ---------- 부모 down ----------

def test_nas_down_sends_one_alert_listing_children():
    states = all_up(nas=down_state(), elum_api=down_state(), elum_web=down_state(), romrom_api=down_state(),
                    romrom_admin=down_state(), romrom_old=down_state())
    transitions = [down_transition(service_id) for service_id in
                   ("nas", "elum-api", "elum-web", "romrom-api", "romrom-admin")]

    notifications, new_states = plan(states, transitions)

    assert len(notifications) == 1
    nas_alert = notifications[0]
    assert (nas_alert.scope, nas_alert.kind, nas_alert.severity) == ("global", "alert", "critical")
    assert nas_alert.title == "[다운] 시놀로지 NAS"
    # 활성 자식만 (paused·retired 제외)
    assert "영향 서비스 3개: 이룸 API, 이룸 웹, 롬롬 API" in nas_alert.body
    assert nas_alert.service_ids == ("nas", "elum-api", "elum-web", "romrom-api")
    assert nas_alert.dedupe_key == f"nas:down:{DOWN_SINCE.isoformat()}"
    assert new_states["nas"].is_down_notified is True
    assert new_states["elum-api"].is_down_notified is False


def test_child_going_down_later_while_parent_down_is_silent():
    states = all_up(nas=down_state(is_down_notified=True, last_notified_at=BASE_TIME), elum_api=down_state(since=BASE_TIME))
    notifications, new_states = plan(states, [down_transition("elum-api", since=BASE_TIME)],
                                     now=BASE_TIME + timedelta(minutes=5))
    assert notifications == []
    assert new_states["elum-api"] == states["elum-api"]


def test_reminder_suppressed_while_parent_down():
    child = down_state(is_down_notified=True, last_notified_at=BASE_TIME - timedelta(hours=7))
    states = all_up(nas=down_state(is_down_notified=True, last_notified_at=BASE_TIME), elum_api=child)
    notifications, new_states = plan(states)
    assert titles(notifications) == []
    assert new_states["elum-api"] == child


def test_child_recovering_while_suppressed_gets_no_recovery_alert():
    # 1틱: NAS·자식 동시 down > NAS 알림만
    states = all_up(nas=down_state(), elum_api=down_state())
    first, states = plan(states, [down_transition("nas"), down_transition("elum-api")])
    assert titles(first) == ["[다운] 시놀로지 NAS"]

    # 2틱: NAS 계속 down, 자식만 복구 > 알린 적 없으므로 복구 알림 없음
    recovered_at = BASE_TIME + timedelta(minutes=5)
    states["elum-api"] = replace(states["elum-api"], status="up", cause=None, since=recovered_at,
                                 consecutive_failures=0, consecutive_successes=2)
    second, _ = plan(states, [recovery_transition("elum-api")], now=recovered_at)
    assert second == []


# ---------- 조상 사슬 (R14 비활성 건너뜀) ----------

def test_multi_level_chain_groups_under_top_ancestor():
    registry = _chain_registry()
    states = all_up(registry, nas=down_state(), docker_host=down_state(), app=down_state())
    notifications, _ = plan(states, [down_transition(service_id) for service_id in ("nas", "docker-host", "app")],
                            registry=registry)
    assert titles(notifications) == ["[다운] 시놀로지 NAS"]
    assert "영향 서비스 2개: 도커 호스트, 앱" in notifications[0].body

    # 중간 부모만 down > 중간 부모 알림 1건에 앱 포함
    states = all_up(registry, docker_host=down_state(), app=down_state())
    notifications, _ = plan(states, registry=registry)
    assert titles(notifications) == ["[다운] 도커 호스트"]
    assert "영향 서비스 1개: 앱" in notifications[0].body


def test_paused_parent_does_not_suppress_child():
    paused_nas_registry = replace(REGISTRY, infrastructure=(ServiceSpec("nas", "시놀로지 NAS", None, status="paused"),))
    states = all_up(paused_nas_registry, nas=down_state(), elum_api=down_state())
    notifications, _ = plan(states, [down_transition("nas"), down_transition("elum-api")],
                            registry=paused_nas_registry)
    assert titles(notifications) == ["[다운] 이룸 API"]


def test_paused_middle_ancestor_is_skipped_and_walk_continues():
    registry = _chain_registry(docker_host_status="paused")
    states = all_up(registry, nas=down_state(is_down_notified=True, last_notified_at=BASE_TIME), app=down_state())
    notifications, _ = plan(states, registry=registry)
    assert notifications == []


# ---------- 실패 연속 보류 (R13) ----------

def test_child_down_held_while_parent_in_failure_streak():
    failing_nas = replace(up_state(since=BASE_TIME - timedelta(minutes=2)), consecutive_failures=2)
    states = all_up(nas=failing_nas, elum_api=down_state())
    notifications, new_states = plan(states, [down_transition("elum-api")])
    assert notifications == []
    assert new_states["elum-api"] == states["elum-api"]


# ---------- 복구 유예 후 묶음 (R12) ----------

def test_parent_recovery_alert_and_child_suppressed_on_recovery_tick():
    # 입력 = advance 직후 (last_notified_at은 아직 down 알림 시각)
    states = all_up(nas=up_state(since=NAS_RECOVERED_AT, last_notified_at=NAS_NOTIFIED_AT), elum_api=down_state())
    notifications, new_states = plan(states, [recovery_transition("nas")], now=NAS_RECOVERED_AT)
    assert titles(notifications) == ["[복구] 시놀로지 NAS"]
    assert (notifications[0].scope, notifications[0].kind) == ("global", "alert")
    assert new_states["nas"].last_notified_at == NAS_RECOVERED_AT
    assert new_states["elum-api"] == states["elum-api"]

    # 유예 기준 = 복구 알림 시각
    within_grace, _ = plan(new_states, now=NAS_RECOVERED_AT + GRACE - timedelta(minutes=1))
    assert within_grace == []


# ---------- 유예 기준 = 복구 알림 (R15, since 재설정 영향 없음) ----------

def test_fresh_start_ancestor_gives_no_hold():
    fresh_nas = up_state(since=BASE_TIME - timedelta(minutes=1))  # INITIAL > up, 알림 이력 없음
    notifications, _ = plan(all_up(nas=fresh_nas, elum_api=down_state()))
    assert titles(notifications) == ["[다운] 이룸 API"]


def test_ancestor_turning_degraded_gives_no_hold():
    degraded_nas = replace(up_state(since=BASE_TIME - timedelta(minutes=1), last_notified_at=BASE_TIME - timedelta(days=2)),
                           status="degraded")
    notifications, _ = plan(all_up(nas=degraded_nas, elum_api=down_state()))
    assert titles(notifications) == ["[다운] 이룸 API"]


def test_ancestor_blip_holds_child_one_tick_only():
    blipping_nas = replace(up_state(since=BASE_TIME), consecutive_failures=1)
    held, states = plan(all_up(nas=blipping_nas, elum_api=down_state()))
    assert held == []

    # 다음 틱: 실패 연속 끊김 (since 재설정) > 보류 없이 개별 알림
    next_tick = BASE_TIME + timedelta(minutes=1)
    states["nas"] = up_state(since=next_tick)
    notifications, _ = plan(states, now=next_tick)
    assert titles(notifications) == ["[다운] 이룸 API"]


def test_children_still_down_after_grace_are_bundled_once():
    states = _nas_just_recovered(elum_api=down_state(), romrom_api=down_state(), romrom_admin=down_state())

    within_grace, states = plan(states, now=NAS_RECOVERED_AT + GRACE - timedelta(minutes=1))
    assert within_grace == []

    bundle_time = NAS_RECOVERED_AT + GRACE
    notifications, states = plan(states, now=bundle_time)
    assert len(notifications) == 1
    bundle = notifications[0]
    assert bundle.title == "[복구 후 계속 다운] 시놀로지 NAS"
    assert (bundle.scope, bundle.kind, bundle.severity) == ("global", "alert", "critical")
    assert "계속 다운 2개: 이룸 API, 롬롬 API" in bundle.body and "원인: 서비스 다운" in bundle.body
    assert bundle.service_ids == ("nas", "elum-api", "romrom-api")
    assert bundle.dedupe_key == f"nas:still-down:{NAS_RECOVERED_AT.isoformat()}"
    assert states["elum-api"].is_down_notified is True and states["elum-api"].last_notified_at == bundle_time
    assert states["romrom-admin"].is_down_notified is False

    again, states = plan(states, now=bundle_time + timedelta(minutes=1))
    assert again == []

    # 묶음에 포함된 자식은 이후 개별 복구 알림
    recovered_at = bundle_time + timedelta(minutes=5)
    states["elum-api"] = up_state(since=recovered_at, last_notified_at=bundle_time)
    recovered, _ = plan(states, [recovery_transition("elum-api")], now=recovered_at)
    assert titles(recovered) == ["[복구] 이룸 API"]


def test_bundle_lists_cause_per_child_when_causes_differ():
    states = _nas_just_recovered(elum_api=down_state(), romrom_api=down_state("external_path"))
    notifications, _ = plan(states, now=NAS_RECOVERED_AT + GRACE)
    assert "계속 다운 2개: 이룸 API (서비스 다운), 롬롬 API (바깥 연결 문제 (프록시/포트포워딩/DNS))" \
        in notifications[0].body


def test_child_going_down_during_grace_alerts_individually_after_grace():
    states = _nas_just_recovered(elum_api=down_state(since=NAS_RECOVERED_AT + timedelta(minutes=2)))
    within_grace, states = plan(states, now=NAS_RECOVERED_AT + timedelta(minutes=5))
    assert within_grace == []
    after_grace, _ = plan(states, now=NAS_RECOVERED_AT + GRACE)
    assert titles(after_grace) == ["[다운] 이룸 API"]


def test_parent_recovery_lists_children_recovered_together():
    states = all_up(nas=up_state(since=BASE_TIME, last_notified_at=NAS_NOTIFIED_AT), elum_api=up_state(since=BASE_TIME))
    notifications, _ = plan(states, [recovery_transition("nas"), recovery_transition("elum-api")],
                            now=DOWN_SINCE + timedelta(hours=1, minutes=12))
    assert titles(notifications) == ["[복구] 시놀로지 NAS"]
    assert "함께 복구된 서비스 1개: 이룸 API" in notifications[0].body


def test_nas_reboot_with_children_two_ticks_late_sends_only_parent_down_and_recovery():
    """advance + 계획 틱 시뮬레이션: NAS 5틱 장애, 자식 10개는 NAS보다 2틱 늦게 복구"""
    children = tuple(ServiceSpec(f"svc-{index}", f"서비스{index}", "elum", depends_on="nas") for index in range(10))
    registry = Registry((ProjectSpec("elum", "이룸"),), children, (ServiceSpec("nas", "시놀로지 NAS", None),))
    nas_timeline = [True] * 2 + [False] * 5 + [True] * 7
    child_timeline = [True] * 2 + [False] * 7 + [True] * 5
    states = {service.id: INITIAL_STATE for service in registry.services + registry.infrastructure}
    sent_titles = []
    for tick_index, (is_nas_ok, is_child_ok) in enumerate(zip(nas_timeline, child_timeline)):
        now = BASE_TIME + timedelta(minutes=tick_index)
        transitions = []
        for service in registry.infrastructure + registry.services:
            is_ok = is_nas_ok if service.id == "nas" else is_child_ok
            result = CheckResult(is_ok, False, 200 if is_ok else None, 100, None if is_ok else "timeout", now)
            states[service.id], transition = advance(
                service.id, states[service.id], Observation(result, None, False), registry.alert, now)
            if transition is not None:
                transitions.append(transition)
        notifications, states = plan(states, transitions, now=now, registry=registry)
        sent_titles.extend(titles(notifications))
    assert sent_titles == ["[다운] 시놀로지 NAS", "[복구] 시놀로지 NAS"]


# ---------- 집 인터넷 ----------

def test_home_network_down_suppresses_external_cause_alerts():
    states = all_up(home_network=down_state("unreachable", is_down_notified=True, last_notified_at=BASE_TIME),
                    elum_docs=down_state("external_path"), romrom_api=down_state("unreachable"))
    notifications, new_states = plan(states, [down_transition("elum-docs", "external_path"),
                                              down_transition("romrom-api", "unreachable")])
    assert notifications == []
    assert new_states["elum-docs"].is_down_notified is False


def test_home_network_down_still_alerts_internal_service_down():
    states = all_up(home_network=down_state("unreachable", is_down_notified=True, last_notified_at=BASE_TIME),
                    elum_docs=down_state("service_down"))
    notifications, _ = plan(states, [down_transition("elum-docs")])
    assert titles(notifications) == ["[다운] 이룸 문서"]


def test_external_cause_held_for_grace_after_home_network_recovers_then_bundled():
    states = all_up(home_network=up_state(since=BASE_TIME, last_notified_at=NAS_NOTIFIED_AT),
                    elum_docs=down_state("external_path"))
    recovering, states = plan(states, [recovery_transition("home-network", cause="unreachable")])
    assert titles(recovering) == ["[복구] 집 인터넷"]

    within_grace, states = plan(states, now=BASE_TIME + timedelta(minutes=9))
    assert within_grace == []

    notifications, _ = plan(states, now=BASE_TIME + GRACE)
    assert titles(notifications) == ["[복구 후 계속 다운] 집 인터넷"]
    assert "계속 다운 1개: 이룸 문서" in notifications[0].body
    assert "바깥 연결 문제 (프록시/포트포워딩/DNS)" in notifications[0].body
