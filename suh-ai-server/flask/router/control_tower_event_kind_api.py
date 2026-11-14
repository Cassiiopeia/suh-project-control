"""관제소 프로젝트 알림 종류 API (nginx API 키 보호): 추가 POST·삭제 DELETE /control/projects/<id>/event-kinds
성공 후 백그라운드 디스코드 동기화 1회 (응답은 기다리지 않음, 디스코드 미설정이면 생략), 런타임 미설정 시 503"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from service.audit_service import AuditAction, AuditCategory
from service.control_tower.discord_sync import DISCORD_SYNC_LOCK, sync_discord
from service.control_tower.event_kind_validation import parse_new_event_kind
from service.control_tower.log_text import sanitize_log_value
from service.control_tower.manage_view import event_kind_entry, load_manage_context
from service.control_tower.runtime import get_runtime
from service.control_tower.sync_registry import load_sync_ready_registry
from util.audit_helper import audited, set_audit_detail
from util.background_runner import run_in_background

logger = logging.getLogger(__name__)

# 변경 후 동기화 스레드 이름 (스레드 덤프 구분용)
SYNC_THREAD_NAME = "control-tower-event-kind-sync"


def register_event_kind_api(blueprint: Blueprint) -> None:
    """알림 종류 API 2개를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/projects/<project_id>/event-kinds", "control_event_kind_create",
                           _create_event_kind, methods=["POST"])
    blueprint.add_url_rule("/control/projects/<project_id>/event-kinds/<kind>", "control_event_kind_delete",
                           _delete_event_kind, methods=["DELETE"])


def _error(code: str, status_code: int, **extra):
    return jsonify({"error": code, **extra}), status_code


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_EVENT_KIND_CREATE)
def _create_event_kind(project_id: str):
    """종류 1개 추가: 검증 > 프로젝트 확인(화면 추가 프로젝트 포함) > 중복 확인·저장 > 동기화 예약"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    # 공개 대상 선택지 = 실효 등록 정보의 discord.roles (등록 파일에서 역할 추가·삭제 시 코드 변경 없음)
    context = load_manage_context(runtime)
    spec, invalid_fields = parse_new_event_kind(request.get_json(silent=True), context.effective.discord)
    if invalid_fields:
        return _error("invalid", 400, fields=invalid_fields)
    if not context.is_known_project(project_id):
        return _error("unknown_project", 404)
    if not runtime.store.insert_project_event_kind(project_id, spec, datetime.now(timezone.utc)):
        return _error("duplicate_kind", 409)

    body = event_kind_entry(spec)
    set_audit_detail({"project_id": project_id, **body})
    _schedule_discord_sync(runtime)
    return jsonify(body), 201


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_EVENT_KIND_DELETE)
def _delete_event_kind(project_id: str, kind: str):
    """종류 1개 삭제 > 동기화 예약 (채널은 지우지 않고 보관 처리, 없는 종류 404)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    # 경로 값은 검증 전 외부 입력 > 정리 후 기록 (404도 시도한 값 남김)
    set_audit_detail({"project_id": sanitize_log_value(project_id), "kind": sanitize_log_value(kind)})
    if not runtime.store.delete_project_event_kind(project_id, kind):
        return _error("unknown_kind", 404)
    _schedule_discord_sync(runtime)
    return "", 204


def _schedule_discord_sync(runtime) -> None:
    """디스코드 설정(클라이언트·서버 ID) 있을 때만 동기화 1회 예약"""
    discord_client = runtime.discord_client_provider() if runtime.discord_client_provider else None
    if discord_client is None or not runtime.guild_id:
        return
    run_in_background(lambda: _sync_discord_after_change(runtime, discord_client), SYNC_THREAD_NAME)


def _sync_discord_after_change(runtime, discord_client) -> None:
    """잠금 대기 > 실효 등록 정보 재조립·준비 확인 > 동기화 (실패는 기록만)"""
    try:
        with DISCORD_SYNC_LOCK:  # 기동 동기화·관리 화면 버튼과 동시 실행 방지 (끝날 때까지 대기)
            registry = load_sync_ready_registry(runtime)
            if registry is None:
                logger.warning("[control-tower event-kind] discord sync skipped : registry is not loaded")
                return
            sync_discord(registry, discord_client, runtime.store, runtime.guild_id)
    except Exception as error:  # 외부 예외 문구는 로그에 싣지 않음
        logger.warning("[control-tower event-kind] discord sync failed : %s", type(error).__name__)
