"""관제소 관리자 화면 API (nginx API 키 보호): overview, 디스코드 동기화, 테스트 알림, 점검 창 설정·해제
런타임 미설정 시 전부 503 unavailable
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from service.control_tower.alert_planner import GLOBAL_SCOPE, Notification
from service.control_tower.discord_sync import sync_discord
from service.control_tower.overview import build_overview
from service.control_tower.registry import SERVICE_STATUS_RETIRED
from service.control_tower.runtime import get_runtime

logger = logging.getLogger(__name__)

# 테스트 알림: 전역은 관제-긴급(alert), 프로젝트는 상태(status) 채널
TEST_ALERT_GLOBAL_KIND = "alert"
TEST_ALERT_PROJECT_KIND = "status"
TEST_ALERT_SEVERITY = "info"
TEST_ALERT_TITLE = "[테스트] 관제소 알림"
TEST_ALERT_BODY = "관제소 알림 경로 확인용 메시지"
# 점검 사유 최대 길이 (글자 수)
MAINTENANCE_REASON_MAX_LENGTH = 200
# 동기화 동시 실행 방지 (관리자 화면 연타)
_sync_lock = threading.Lock()


def register_admin_api(blueprint: Blueprint) -> None:
    """관리자 API 5개를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/overview", "control_overview", _overview, methods=["GET"])
    blueprint.add_url_rule("/control/discord/sync", "control_discord_sync", _sync, methods=["POST"])
    blueprint.add_url_rule("/control/test-alert", "control_test_alert", _test_alert, methods=["POST"])
    blueprint.add_url_rule("/control/maintenance", "control_maintenance_set", _set_maintenance, methods=["POST"])
    blueprint.add_url_rule("/control/maintenance/<service_id>", "control_maintenance_clear", _clear_maintenance,
                           methods=["DELETE"])


def _unavailable():
    return jsonify({"error": "unavailable"}), 503


def _invalid(*field_names: str):
    return jsonify({"error": "invalid", "fields": list(field_names)}), 400


def _overview():
    runtime = get_runtime()
    if runtime is None:
        return _unavailable()
    return jsonify(build_overview(runtime, datetime.now(timezone.utc)))


def _sync():
    """디스코드 동기화 1회 (동기 실행): 설정 확인 > 동시 실행 차단 > 동기화 > 리포트"""
    runtime = get_runtime()
    if runtime is None:
        return _unavailable()
    discord_client = runtime.discord_client_provider() if runtime.discord_client_provider else None
    if discord_client is None or not runtime.guild_id:
        return jsonify({"error": "discord_not_configured"}), 503
    if not _sync_lock.acquire(blocking=False):
        return jsonify({"error": "sync_in_progress"}), 409
    try:
        report = sync_discord(runtime.registry_provider(), discord_client, runtime.store, runtime.guild_id)
    except Exception as error:  # 외부 예외 문구는 응답·로그에 싣지 않음
        logger.warning("[control-tower admin] discord sync failed : %s", type(error).__name__)
        return jsonify({"error": "sync_failed"}), 500
    finally:
        _sync_lock.release()
    return jsonify(asdict(report))


def _test_alert():
    """테스트 알림 1건: 대상 확인(global | 등록된 프로젝트) > 발송"""
    runtime = get_runtime()
    if runtime is None:
        return _unavailable()
    payload = request.get_json(silent=True)
    scope = payload.get("scope") if isinstance(payload, dict) else None
    project_ids = {project.id for project in runtime.registry_provider().projects}
    if not isinstance(scope, str) or (scope != GLOBAL_SCOPE and scope not in project_ids):
        return _invalid("scope")
    notification = Notification(
        scope=scope, kind=TEST_ALERT_GLOBAL_KIND if scope == GLOBAL_SCOPE else TEST_ALERT_PROJECT_KIND,
        severity=TEST_ALERT_SEVERITY, title=TEST_ALERT_TITLE, body=TEST_ALERT_BODY, service_ids=(), dedupe_key="")
    try:
        is_sent = runtime.dispatcher.dispatch(notification) is True
    except Exception as error:
        logger.warning("[control-tower admin] test alert failed : %s", type(error).__name__)
        is_sent = False
    return jsonify({"sent": is_sent})


def _set_maintenance():
    """점검 창 설정: 필드 검증(service_id, until, reason) > 서비스 확인 > 저장"""
    runtime = get_runtime()
    if runtime is None:
        return _unavailable()
    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    service_id, reason = payload.get("service_id"), payload.get("reason")
    until = _parse_future_moment(payload.get("until"))

    invalid_fields = []
    if not isinstance(service_id, str):
        invalid_fields.append("service_id")
    if until is None:
        invalid_fields.append("until")
    if reason is not None and (not isinstance(reason, str) or len(reason) > MAINTENANCE_REASON_MAX_LENGTH):
        invalid_fields.append("reason")
    if invalid_fields:
        return _invalid(*invalid_fields)

    registry = runtime.registry_provider()
    service = registry.service_by_id(service_id)
    if service is None or service.status == SERVICE_STATUS_RETIRED:
        return jsonify({"error": "unknown_service"}), 404
    runtime.store.set_maintenance(service_id, until, reason or "")
    return jsonify({"ok": True})


def _clear_maintenance(service_id: str):
    """점검 창 해제 (없어도 성공)"""
    runtime = get_runtime()
    if runtime is None:
        return _unavailable()
    runtime.store.clear_maintenance(service_id)
    return jsonify({"ok": True})


def _parse_future_moment(value) -> datetime | None:
    """시간대 포함 ISO 8601이고 지금보다 미래일 때만 aware datetime, 그 외 None ('Z' 접미사 허용)"""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if moment.tzinfo is None or moment <= datetime.now(timezone.utc):
        return None
    return moment
