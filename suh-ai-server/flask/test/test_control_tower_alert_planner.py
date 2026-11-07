"""관제소 알림 계획: 부모 묶음, 점검 중, 재알림, 복구 다운 시간, 생명주기, 집 인터넷 억제, 재기동 복원"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from service.control_tower.alert_planner import Notification, plan_notifications
from service.control_tower.alert_texts import format_duration_korean
from service.control_tower.registry import MaintenanceWindow, ProjectSpec, Registry, ServiceSpec
from service.control_tower.state_machine import INITIAL_STATE, ServiceState, Transition

BASE_TIME = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)  # KST 09:00
DOWN_SINCE = BASE_TIME - timedelta(minutes=3)  # KST 08:57

REGISTRY = Registry(
    projects=(ProjectSpec("elum", "이룸"), ProjectSpec("romrom", "롬롬")),
    services=(
        ServiceSpec("elum-api", "이룸 API", "elum", depends_on="nas"),
        ServiceSpec("elum-web", "이룸 웹", "elum", depends_on="nas"),
        ServiceSpec("romrom-api", "롬롬 API", "romrom", depends_on="nas"),
        ServiceSpec("romrom-admin", "롬롬 관리자", "romrom", status="paused", depends_on="nas"),
        ServiceSpec("romrom-old", "롬롬 구버전", "romrom", status="retired", depends_on="nas"),
        ServiceSpec("elum-docs", "이룸 문서", "elum"),
    ),
    infrastructure=(
        ServiceSpec("nas", "시놀로지 NAS", None),
        ServiceSpec("home-network", "집 인터넷", None),
    ),
)


def _up() -> ServiceState:
    return replace(INITIAL_STATE, status="up", since=BASE_TIME - timedelta(days=1))


def _down(cause: str = "service_down", is_down_notified: bool = False,
          last_notified_at: datetime | None = None, since: datetime = DOWN_SINCE) -> ServiceState:
    return ServiceState("down", 3, 0, cause, since, last_notified_at, is_down_notified)


def _down_transition(service_id: str, cause: str = "service_down", since: datetime = DOWN_SINCE) -> Transition:
    return Transition(service_id, "up", "down", cause, since)


def _recovery_transition(service_id: str, since: datetime, cause: str = "service_down") -> Transition:
    return Transition(service_id, "down", "up", cause, since)


def _all_up(**overrides: ServiceState) -> dict[str, ServiceState]:
    states = {service.id: _up() for service in REGISTRY.services + REGISTRY.infrastructure}
    states.update({service_id.replace("_", "-"): state for service_id, state in overrides.items()})
    return states


def _plan(states, transitions=(), maintenance=None, now=BASE_TIME):
    return plan_notifications(REGISTRY, states, list(transitions), maintenance or {}, now)


# ---------- 부모 묶음 ----------

def test_nas_down_sends_one_alert_listing_children():
    states = _all_up(nas=_down(), elum_api=_down(), elum_web=_down(), romrom_api=_down(),
                     romrom_admin=_down(), romrom_old=_down())
    transitions = [_down_transition(service_id) for service_id in
                   ("nas", "elum-api", "elum-web", "romrom-api", "romrom-admin")]

    notifications, new_states = _plan(states, transitions)

    assert len(notifications) == 1
    nas_alert = notifications[0]
    assert isinstance(nas_alert, Notification)
    assert (nas_alert.scope, nas_alert.kind, nas_alert.severity) == ("global", "alert", "critical")
    assert nas_alert.title == "[다운] 시놀로지 NAS"
    # 활성 자식만 (paused·retired 제외)
    assert "영향 서비스 3개: 이룸 API, 이룸 웹, 롬롬 API" in nas_alert.body
    assert nas_alert.service_ids == ("nas", "elum-api", "elum-web", "romrom-api")
    assert nas_alert.dedupe_key == f"nas:down:{DOWN_SINCE.isoformat()}"
    assert new_states["nas"].is_down_notified is True
    assert new_states["nas"].last_notified_at == BASE_TIME


def test_child_going_down_later_while_parent_down_is_silent():
    states = _all_up(nas=_down(is_down_notified=True, last_notified_at=BASE_TIME),
                     elum_api=_down(since=BASE_TIME))
    notifications, new_states = _plan(states, [_down_transition("elum-api", since=BASE_TIME)],
                                      now=BASE_TIME + timedelta(minutes=5))
    assert notifications == []
    assert new_states["elum-api"].is_down_notified is False


def test_child_still_down_after_parent_recovers_alerts_once():
    nas_since = DOWN_SINCE
    states = _all_up(nas=_up(), elum_api=_down())
    recovery_time = BASE_TIME + timedelta(minutes=30)

    # 부모 복구 틱: 자식 개별 알림 없음, 부모 복구 알림만
    first, states_after_first = _plan(states, [_recovery_transition("nas", nas_since)], now=recovery_time)
    assert [notification.title for notification in first] == []

    # 다음 계획 호출: 여전히 down인 자식 개별 알림 1회
    second, states_after_second = _plan(states_after_first, now=recovery_time + timedelta(minutes=1))
    assert [notification.title for notification in second] == ["[다운] 이룸 API"]
    assert second[0].scope == "elum" and second[0].kind == "status"
    assert states_after_second["elum-api"].is_down_notified is True

    third, _ = _plan(states_after_second, now=recovery_time + timedelta(minutes=2))
    assert third == []


def test_parent_recovery_is_announced_when_parent_was_notified():
    states = _all_up(nas=replace(_up(), since=BASE_TIME), elum_api=replace(_up(), since=BASE_TIME))
    states["nas"] = replace(states["nas"], last_notified_at=DOWN_SINCE + timedelta(minutes=3))
    transitions = [_recovery_transition("nas", DOWN_SINCE), _recovery_transition("elum-api", DOWN_SINCE)]

    notifications, _ = _plan(states, transitions, now=DOWN_SINCE + timedelta(hours=1, minutes=12))

    assert len(notifications) == 1
    assert notifications[0].title == "[복구] 시놀로지 NAS"
    assert "함께 복구된 서비스 1개: 이룸 API" in notifications[0].body


def test_child_recovering_while_suppressed_gets_no_recovery_alert():
    states = _all_up(nas=_down(is_down_notified=True, last_notified_at=BASE_TIME))
    notifications, _ = _plan(states, [_recovery_transition("elum-api", DOWN_SINCE)],
                             now=BASE_TIME + timedelta(minutes=10))
    assert notifications == []


# ---------- 점검 중 ----------

def test_maintenance_service_gets_no_alert_and_flags_untouched():
    states = _all_up(elum_docs=_down())
    maintenance = {"elum-docs": MaintenanceWindow("elum-docs", BASE_TIME + timedelta(hours=1), "업데이트")}
    notifications, new_states = _plan(states, [_down_transition("elum-docs")], maintenance)
    assert notifications == []
    assert new_states["elum-docs"] == states["elum-docs"]


def test_maintenance_end_while_down_alerts_once():
    states = _all_up(elum_docs=_down())
    maintenance = {"elum-docs": MaintenanceWindow("elum-docs", BASE_TIME + timedelta(hours=1), "업데이트")}
    during, states = _plan(states, maintenance=maintenance, now=BASE_TIME + timedelta(minutes=30))
    assert during == []

    after, states = _plan(states, maintenance=maintenance, now=BASE_TIME + timedelta(hours=1, minutes=1))
    assert [notification.title for notification in after] == ["[다운] 이룸 문서"]

    again, _ = _plan(states, maintenance=maintenance, now=BASE_TIME + timedelta(hours=1, minutes=2))
    assert again == []


def test_recovery_during_maintenance_is_silent():
    states = _all_up(elum_docs=replace(_up(), last_notified_at=BASE_TIME))
    maintenance = {"elum-docs": MaintenanceWindow("elum-docs", BASE_TIME + timedelta(hours=2), "")}
    notifications, _ = _plan(states, [_recovery_transition("elum-docs", DOWN_SINCE)], maintenance,
                             now=BASE_TIME + timedelta(hours=1))
    assert notifications == []


# ---------- 재알림 ----------

def test_reminder_after_six_hours():
    notified_at = BASE_TIME
    states = _all_up(elum_docs=_down(is_down_notified=True, last_notified_at=notified_at))

    early, _ = _plan(states, now=notified_at + timedelta(hours=5, minutes=59))
    assert early == []

    reminder_time = notified_at + timedelta(hours=6)
    notifications, new_states = _plan(states, now=reminder_time)
    assert len(notifications) == 1
    reminder = notifications[0]
    assert reminder.title == "[계속 다운] 이룸 문서"
    assert reminder.severity == "critical"
    assert reminder.dedupe_key == f"elum-docs:reminder-1:{DOWN_SINCE.isoformat()}"
    assert new_states["elum-docs"].last_notified_at == reminder_time

    # 다음 재알림은 갱신된 시각 기준
    quiet, _ = _plan(new_states, now=reminder_time + timedelta(hours=1))
    assert quiet == []
    second, _ = _plan(new_states, now=reminder_time + timedelta(hours=6))
    assert second[0].dedupe_key == f"elum-docs:reminder-2:{DOWN_SINCE.isoformat()}"


# ---------- 복구 ----------

def test_recovery_body_has_duration():
    recovery_time = DOWN_SINCE + timedelta(hours=1, minutes=12)
    states = _all_up(elum_docs=replace(_up(), since=recovery_time, last_notified_at=BASE_TIME))
    notifications, _ = _plan(states, [_recovery_transition("elum-docs", DOWN_SINCE)], now=recovery_time)

    assert len(notifications) == 1
    recovery = notifications[0]
    assert recovery.title == "[복구] 이룸 문서"
    assert recovery.severity == "recovered"
    assert (recovery.scope, recovery.kind) == ("elum", "status")
    assert "다운 시간: 1시간 12분" in recovery.body
    assert "원인: 서비스 다운" in recovery.body
    assert "시작: 2026-11-06 08:57 KST" in recovery.body
    assert recovery.dedupe_key == f"elum-docs:recovered:{DOWN_SINCE.isoformat()}"


def test_recovery_without_prior_down_alert_is_silent():
    # 이전 장애 알림 시각은 이번 장애 시작 이전 > 이번 장애는 알린 적 없음
    states = _all_up(elum_docs=replace(_up(), last_notified_at=DOWN_SINCE - timedelta(days=2)))
    notifications, _ = _plan(states, [_recovery_transition("elum-docs", DOWN_SINCE)])
    assert notifications == []


def test_up_degraded_transition_is_not_announced():
    states = _all_up(elum_docs=replace(_up(), status="degraded"))
    notifications, _ = _plan(states, [Transition("elum-docs", "up", "degraded", None, BASE_TIME)])
    assert notifications == []


# ---------- 생명주기 ----------

def test_paused_service_never_alerts():
    paused_registry = replace(REGISTRY, services=(ServiceSpec("elum-docs", "이룸 문서", "elum", status="paused"),))
    states = {"elum-docs": _down()}
    down_notifications, _ = plan_notifications(paused_registry, states, [_down_transition("elum-docs")], {}, BASE_TIME)
    reminder_states = {"elum-docs": _down(is_down_notified=True, last_notified_at=BASE_TIME - timedelta(days=1))}
    reminder_notifications, _ = plan_notifications(paused_registry, reminder_states, [], {}, BASE_TIME)
    recovery_states = {"elum-docs": replace(_up(), last_notified_at=BASE_TIME)}
    recovery_notifications, _ = plan_notifications(
        paused_registry, recovery_states, [_recovery_transition("elum-docs", DOWN_SINCE)], {}, BASE_TIME)
    assert down_notifications == reminder_notifications == recovery_notifications == []


# ---------- 집 인터넷 ----------

def test_home_network_down_suppresses_external_cause_alerts():
    states = _all_up(home_network=_down("unreachable", is_down_notified=True, last_notified_at=BASE_TIME),
                     elum_docs=_down("external_path"), romrom_api=_down("unreachable"))
    notifications, new_states = _plan(states, [_down_transition("elum-docs", "external_path"),
                                               _down_transition("romrom-api", "unreachable")])
    assert notifications == []
    assert new_states["elum-docs"].is_down_notified is False


def test_home_network_down_still_alerts_internal_service_down():
    states = _all_up(home_network=_down("unreachable", is_down_notified=True, last_notified_at=BASE_TIME),
                     elum_docs=_down("service_down"))
    notifications, _ = _plan(states, [_down_transition("elum-docs")])
    assert [notification.title for notification in notifications] == ["[다운] 이룸 문서"]
    assert "원인: 서비스 다운" in notifications[0].body


def test_external_cause_alerts_once_after_home_network_recovers():
    states = _all_up(elum_docs=_down("external_path"))
    recovering, states = _plan(states, [_recovery_transition("home-network", DOWN_SINCE, "unreachable")])
    assert all("이룸 문서" not in notification.title for notification in recovering)

    notifications, _ = _plan(states, now=BASE_TIME + timedelta(minutes=1))
    assert [notification.title for notification in notifications] == ["[다운] 이룸 문서"]
    assert "바깥 연결 문제 (프록시/포트포워딩/DNS)" in notifications[0].body


# ---------- 재기동 복원 ----------

def test_restart_with_restored_down_state_does_not_resend():
    restored = {"elum-docs": _down(is_down_notified=True, last_notified_at=BASE_TIME - timedelta(hours=1))}
    notifications, new_states = _plan(_all_up(**{"elum_docs": restored["elum-docs"]}))
    assert notifications == []
    assert new_states["elum-docs"] == restored["elum-docs"]


def test_restored_down_state_not_yet_notified_alerts_once():
    states = _all_up(elum_docs=_down())
    notifications, new_states = _plan(states)
    assert [notification.title for notification in notifications] == ["[다운] 이룸 문서"]
    assert new_states["elum-docs"].is_down_notified is True


def test_input_states_are_not_mutated():
    states = _all_up(elum_docs=_down())
    snapshot = dict(states)
    _plan(states, [_down_transition("elum-docs")])
    assert states == snapshot


# ---------- 문구 ----------

def test_format_duration_korean():
    assert format_duration_korean(30) == "1분 미만"
    assert format_duration_korean(5 * 60) == "5분"
    assert format_duration_korean(72 * 60) == "1시간 12분"
    assert format_duration_korean(3600) == "1시간"
    assert format_duration_korean((2 * 24 + 3) * 3600 + 59 * 60) == "2일 3시간"
