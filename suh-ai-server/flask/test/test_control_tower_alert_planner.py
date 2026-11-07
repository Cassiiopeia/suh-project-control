"""관제소 알림 계획 기본: down·재알림·복구 다운 시간, 점검 중, 생명주기, 재기동 복원, 기간 표기"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from control_tower_alert_fixtures import (
    BASE_TIME, DOWN_SINCE, REGISTRY, all_up, down_state, down_transition, plan, recovery_transition, titles,
    up_state,
)
from service.control_tower.alert_planner import Notification, plan_notifications
from service.control_tower.alert_texts import format_duration_korean
from service.control_tower.registry import MaintenanceWindow, ServiceSpec
from service.control_tower.state_machine import Transition


# ---------- down ----------

def test_single_service_down_alerts_to_project_status_channel():
    notifications, new_states = plan(all_up(elum_docs=down_state()), [down_transition("elum-docs")])
    assert len(notifications) == 1
    alert = notifications[0]
    assert isinstance(alert, Notification)
    assert (alert.scope, alert.kind, alert.severity) == ("elum", "status", "critical")
    assert alert.title == "[다운] 이룸 문서"
    assert "원인: 서비스 다운" in alert.body and "시작: 2026-11-06 08:57 KST" in alert.body
    assert alert.dedupe_key == f"elum-docs:down:{DOWN_SINCE.isoformat()}"
    assert new_states["elum-docs"].is_down_notified is True
    assert new_states["elum-docs"].last_notified_at == BASE_TIME


# ---------- 점검 중 ----------

def test_maintenance_service_gets_no_alert_and_flags_untouched():
    states = all_up(elum_docs=down_state())
    maintenance = {"elum-docs": MaintenanceWindow("elum-docs", BASE_TIME + timedelta(hours=1), "업데이트")}
    notifications, new_states = plan(states, [down_transition("elum-docs")], maintenance)
    assert notifications == []
    assert new_states["elum-docs"] == states["elum-docs"]


def test_maintenance_end_while_down_alerts_once():
    states = all_up(elum_docs=down_state())
    maintenance = {"elum-docs": MaintenanceWindow("elum-docs", BASE_TIME + timedelta(hours=1), "업데이트")}
    during, states = plan(states, maintenance=maintenance, now=BASE_TIME + timedelta(minutes=30))
    assert during == []

    after, states = plan(states, maintenance=maintenance, now=BASE_TIME + timedelta(hours=1, minutes=1))
    assert titles(after) == ["[다운] 이룸 문서"]

    again, _ = plan(states, maintenance=maintenance, now=BASE_TIME + timedelta(hours=1, minutes=2))
    assert again == []


def test_recovery_during_maintenance_is_silent():
    states = all_up(elum_docs=up_state(last_notified_at=BASE_TIME))
    maintenance = {"elum-docs": MaintenanceWindow("elum-docs", BASE_TIME + timedelta(hours=2), "")}
    notifications, _ = plan(states, [recovery_transition("elum-docs")], maintenance, now=BASE_TIME + timedelta(hours=1))
    assert notifications == []


# ---------- 재알림 ----------

def test_reminder_after_six_hours():
    notified_at = BASE_TIME
    states = all_up(elum_docs=down_state(is_down_notified=True, last_notified_at=notified_at))

    early, _ = plan(states, now=notified_at + timedelta(hours=5, minutes=59))
    assert early == []

    reminder_time = notified_at + timedelta(hours=6)
    notifications, new_states = plan(states, now=reminder_time)
    assert len(notifications) == 1
    reminder = notifications[0]
    assert reminder.title == "[계속 다운] 이룸 문서"
    assert reminder.severity == "critical"
    assert reminder.dedupe_key == f"elum-docs:reminder-1:{DOWN_SINCE.isoformat()}"
    assert new_states["elum-docs"].last_notified_at == reminder_time

    # 다음 재알림은 갱신된 시각 기준
    quiet, _ = plan(new_states, now=reminder_time + timedelta(hours=1))
    assert quiet == []
    second, _ = plan(new_states, now=reminder_time + timedelta(hours=6))
    assert second[0].dedupe_key == f"elum-docs:reminder-2:{DOWN_SINCE.isoformat()}"


# ---------- 복구 ----------

def test_recovery_body_has_duration():
    recovery_time = DOWN_SINCE + timedelta(hours=1, minutes=12)
    states = all_up(elum_docs=up_state(since=recovery_time, last_notified_at=BASE_TIME))
    notifications, _ = plan(states, [recovery_transition("elum-docs")], now=recovery_time)

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
    states = all_up(elum_docs=up_state(last_notified_at=DOWN_SINCE - timedelta(days=2)))
    notifications, _ = plan(states, [recovery_transition("elum-docs")])
    assert notifications == []


def test_up_degraded_transition_is_not_announced():
    states = all_up(elum_docs=replace(up_state(), status="degraded"))
    notifications, _ = plan(states, [Transition("elum-docs", "up", "degraded", None, BASE_TIME)])
    assert notifications == []


# ---------- 생명주기 ----------

def test_paused_service_never_alerts():
    paused_registry = replace(REGISTRY, services=(ServiceSpec("elum-docs", "이룸 문서", "elum", status="paused"),))
    down_notifications, _ = plan_notifications(
        paused_registry, {"elum-docs": down_state()}, [down_transition("elum-docs")], {}, BASE_TIME)
    reminder_states = {"elum-docs": down_state(is_down_notified=True, last_notified_at=BASE_TIME - timedelta(days=1))}
    reminder_notifications, _ = plan_notifications(paused_registry, reminder_states, [], {}, BASE_TIME)
    recovery_states = {"elum-docs": up_state(last_notified_at=BASE_TIME)}
    recovery_notifications, _ = plan_notifications(
        paused_registry, recovery_states, [recovery_transition("elum-docs")], {}, BASE_TIME)
    assert down_notifications == reminder_notifications == recovery_notifications == []


# ---------- 재기동 복원 ----------

def test_restart_with_restored_down_state_does_not_resend():
    restored = down_state(is_down_notified=True, last_notified_at=BASE_TIME - timedelta(hours=1))
    notifications, new_states = plan(all_up(elum_docs=restored))
    assert notifications == []
    assert new_states["elum-docs"] == restored


def test_restored_down_state_not_yet_notified_alerts_once():
    notifications, new_states = plan(all_up(elum_docs=down_state()))
    assert titles(notifications) == ["[다운] 이룸 문서"]
    assert new_states["elum-docs"].is_down_notified is True


def test_input_states_are_not_mutated():
    states = all_up(elum_docs=down_state())
    snapshot = dict(states)
    plan(states, [down_transition("elum-docs")])
    assert states == snapshot


# ---------- 문구 ----------

def test_format_duration_korean():
    assert format_duration_korean(30) == "1분 미만"
    assert format_duration_korean(5 * 60) == "5분"
    assert format_duration_korean(72 * 60) == "1시간 12분"
    assert format_duration_korean(3600) == "1시간"
    assert format_duration_korean((2 * 24 + 3) * 3600 + 59 * 60) == "2일 3시간"
