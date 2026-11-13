"""관제소 프로젝트 받을 곳 API (nginx API 키 보호): 추가 POST /control/projects/<id>/destinations,
사용 전환 PATCH·삭제 DELETE /control/destinations/<id>, 테스트 발송 POST /control/destinations/<id>/test
URL 원문은 암호화 저장만 (응답·감사·로그는 url_hint까지), 비밀값 없으면 추가·사용 켜기·테스트 409 (끄기·삭제는 가능), 런타임 미설정 시 503"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from service.audit_service import AuditAction, AuditCategory
from service.control_tower.check_runner import utc_now
from service.control_tower.destination_delivery import (
    RESULT_SENT, DestinationDeliverer, DestinationSecretNotConfiguredError, describe_url_hint, encrypt_destination_url,
)
from service.control_tower.destination_validation import (
    destination_audit_detail, destination_entry, destination_kind_choices, parse_new_destination,
)
from service.control_tower.log_text import sanitize_log_value
from service.control_tower.manage_view import load_manage_context
from service.control_tower.project_event_tokens import is_token_secret_configured
from service.control_tower.runtime import get_runtime
from util.audit_helper import audited, set_audit_detail
from util.background_runner import run_in_background


def register_destination_api(blueprint: Blueprint) -> None:
    """받을 곳 API 4개를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/projects/<project_id>/destinations", "control_destination_create",
                           _create_destination, methods=["POST"])
    blueprint.add_url_rule("/control/destinations/<int:destination_id>", "control_destination_update",
                           _update_destination, methods=["PATCH"])
    blueprint.add_url_rule("/control/destinations/<int:destination_id>", "control_destination_delete",
                           _delete_destination, methods=["DELETE"])
    blueprint.add_url_rule("/control/destinations/<int:destination_id>/test", "control_destination_test",
                           _test_destination, methods=["POST"])


def _error(code: str, status_code: int, **extra):
    return jsonify({"error": code, **extra}), status_code


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_DESTINATION_CREATE)
def _create_destination(project_id: str):
    """받을 곳 1개 추가: 프로젝트 확인 > 검증(종류·이름·URL) > 비밀값 확인 > 암호화 저장 > 힌트만 응답"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    # 경로 값은 외부 입력 > 정리 후 기록 (URL은 어떤 결과에도 기록하지 않음)
    set_audit_detail({"project_id": sanitize_log_value(project_id)})
    if not load_manage_context(runtime).is_known_project(project_id):
        return _error("unknown_project", 404)
    new_destination, invalid_fields = parse_new_destination(
        request.get_json(silent=True), destination_kind_choices(runtime.store, project_id))
    if invalid_fields:
        return _error("invalid", 400, fields=invalid_fields)
    try:
        url_encrypted, encryption_scheme = encrypt_destination_url(new_destination.url, os.environ)
    except DestinationSecretNotConfiguredError:
        return _error("secret_not_configured", 409)
    destination_id = runtime.store.insert_destination(
        project_id, new_destination.kind, new_destination.label, url_encrypted, encryption_scheme,
        describe_url_hint(new_destination.url), utc_now())
    destination = runtime.store.find_destination(destination_id)
    set_audit_detail(destination_audit_detail(destination))
    body = destination_entry(destination)
    return jsonify({key: body[key] for key in ("destination_id", "kind", "label", "url_hint", "is_enabled")}), 201


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_DESTINATION_UPDATE)
def _update_destination(destination_id: int):
    """사용·중지 전환: 본문 검증 > 받을 곳 확인 > 비밀값 확인(켜기만) > 저장 > 항목 응답"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    set_audit_detail({"destination_id": destination_id})
    payload = request.get_json(silent=True)
    is_enabled = payload.get("is_enabled") if isinstance(payload, dict) else None
    if not isinstance(is_enabled, bool):
        return _error("invalid", 400, fields=["is_enabled"])
    destination = runtime.store.find_destination(destination_id)
    if destination is None:
        return _error("unknown_destination", 404)
    set_audit_detail({**destination_audit_detail(destination), "is_enabled": is_enabled})
    # 끄기는 비밀값 없어도 허용 (비밀값 분실 시에도 발송 중지 가능)
    if is_enabled and not is_token_secret_configured():
        return _error("secret_not_configured", 409)
    if not runtime.store.set_destination_enabled(destination_id, is_enabled):
        return _error("unknown_destination", 404)
    return jsonify(destination_entry(runtime.store.find_destination(destination_id))), 200


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_DESTINATION_DELETE)
def _delete_destination(destination_id: int):
    """받을 곳 1개 삭제 (비밀값 없어도 가능, 없는 받을 곳 404)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    set_audit_detail({"destination_id": destination_id})
    destination = runtime.store.find_destination(destination_id)
    if destination is None or not runtime.store.delete_destination(destination_id):
        return _error("unknown_destination", 404)
    set_audit_detail(destination_audit_detail(destination))
    return "", 204


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_DESTINATION_TEST)
def _test_destination(destination_id: int):
    """고정 문구 1건 테스트 발송 (요청 안에서 기다림, 제한 시간은 destination_delivery 상수) > 결과 코드 응답"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    set_audit_detail({"destination_id": destination_id})
    destination = runtime.store.find_destination(destination_id)
    if destination is None:
        return _error("unknown_destination", 404)
    set_audit_detail(destination_audit_detail(destination))
    # 받을 곳 1개 발송 경로 재사용 (발송·결과 기록·로그 규칙 동일, 테스트 발송은 결과 캐시 불필요)
    deliverer = DestinationDeliverer(runtime.store, run_in_background, os.environ)
    try:
        result = deliverer.send_test_message(destination)
    except DestinationSecretNotConfiguredError:
        return _error("secret_not_configured", 409)
    return jsonify({"is_sent": result == RESULT_SENT, "result": result}), 200
