"""관제소 프로젝트 이벤트 토큰 API (nginx API 키 보호): 발급·교체 POST·폐기 DELETE /control/projects/<id>/event-token
토큰 원문은 발급 응답에만 (감사·로그는 project_id만), 런타임 미설정 시 503"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify

from service.audit_service import AuditAction, AuditCategory
from service.control_tower.log_text import sanitize_log_value
from service.control_tower.manage_view import load_manage_context
from service.control_tower.project_event_tokens import (
    TokenSecretNotConfiguredError, describe_project_token, issue_project_token, revoke_project_tokens,
)
from service.control_tower.runtime import get_runtime
from util.audit_helper import audited, set_audit_detail


def register_event_token_api(blueprint: Blueprint) -> None:
    """이벤트 토큰 API 2개를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/projects/<project_id>/event-token", "control_event_token_issue",
                           _issue_event_token, methods=["POST"])
    blueprint.add_url_rule("/control/projects/<project_id>/event-token", "control_event_token_revoke",
                           _revoke_event_token, methods=["DELETE"])


def _error(code: str, status_code: int):
    return jsonify({"error": code}), status_code


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_EVENT_TOKEN_ISSUE)
def _issue_event_token(project_id: str):
    """발급·교체: 프로젝트 확인(화면 추가 프로젝트 포함) > 발급(기존 현재는 이전으로) > 원문 + 이전 만료 시각"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    # 경로 값은 외부 입력 > 정리 후 기록 (토큰 값은 기록하지 않음)
    set_audit_detail({"project_id": sanitize_log_value(project_id)})
    if not load_manage_context(runtime).is_known_project(project_id):
        return _error("unknown_project", 404)
    now = datetime.now(timezone.utc)
    try:
        token = issue_project_token(runtime.store, project_id, now)
    except TokenSecretNotConfiguredError:
        return _error("secret_not_configured", 409)
    token_status = describe_project_token(runtime.store, project_id, now)
    return jsonify({"token": token, "previous_expires_at": token_status["previous_expires_at"]}), 201


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_EVENT_TOKEN_REVOKE)
def _revoke_event_token(project_id: str):
    """현재·이전 토큰 폐기: 프로젝트 확인 > 삭제 (DB 관리 유지, 지울 토큰 없으면 404)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    set_audit_detail({"project_id": sanitize_log_value(project_id)})
    # 등록된 id만 저장소·로그로 전달 (검증 전 경로 값이 로그에 실리지 않게)
    if not load_manage_context(runtime).is_known_project(project_id):
        return _error("unknown_project", 404)
    if not revoke_project_tokens(runtime.store, project_id):
        return _error("no_token", 404)
    return "", 204
