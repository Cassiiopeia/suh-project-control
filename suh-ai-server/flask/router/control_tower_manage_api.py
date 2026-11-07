"""관제소 서비스 관리 API (nginx API 키 보호): 관리 목록·정보, 서비스·프로젝트 덮어쓰기·추가·삭제, 상태 페이지, DNS 후보
변경은 저장소에만 기록 > 다음 폴러 틱(60초 안)에 감시·Worker 스냅샷 반영, 런타임 미설정 시 전부 503"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from config.control_tower_config import MAX_EXTERNAL_CHECKS
from service.audit_service import AuditAction, AuditCategory
from service.control_tower.dns_candidates import (
    CLOUDFLARE_API_TOKEN_ENV, CLOUDFLARE_ZONE_NAME_ENV, DEFAULT_CLOUDFLARE_ZONE_NAME, DnsLookupError,
    fetch_dns_candidates, registered_hosts,
)
from service.control_tower.manage_view import (
    build_manage, build_service_detail, count_external_checks, load_manage_context,
)
from service.control_tower.override_models import CustomProject, CustomService, ServiceOverride
from service.control_tower.override_validation import (
    PROJECT_PATCH_VALIDATORS, SERVICE_PATCH_VALIDATORS, STATUS_PAGE_PATCH_VALIDATORS, parse_new_project,
    parse_new_service, parse_patch,
)
from service.control_tower.registry import SERVICE_STATUS_RETIRED
from service.control_tower.registry_overrides import merge_overrides
from service.control_tower.runtime import get_runtime
from util.audit_helper import audited, set_audit_detail

# 인프라 항목에서 덮어쓸 수 없는 칸 (공개 페이지·Worker 점검 대상이 아님)
INFRASTRUCTURE_LOCKED_FIELDS = ("is_public", "external_url")


def register_manage_api(blueprint: Blueprint) -> None:
    """관리 API 9개를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/manage", "control_manage", _manage, methods=["GET"])
    blueprint.add_url_rule("/control/services", "control_service_create", _create_service, methods=["POST"])
    blueprint.add_url_rule("/control/services/<service_id>", "control_service_detail", _service_detail,
                           methods=["GET"])
    blueprint.add_url_rule("/control/services/<service_id>", "control_service_update", _update_service,
                           methods=["PATCH"])
    blueprint.add_url_rule("/control/services/<service_id>", "control_service_delete", _delete_service,
                           methods=["DELETE"])
    blueprint.add_url_rule("/control/projects", "control_project_create", _create_project, methods=["POST"])
    blueprint.add_url_rule("/control/projects/<project_id>", "control_project_update", _update_project,
                           methods=["PATCH"])
    blueprint.add_url_rule("/control/status-page", "control_status_page_update", _update_status_page,
                           methods=["PATCH"])
    blueprint.add_url_rule("/control/dns-candidates", "control_dns_candidates", _dns_candidates, methods=["GET"])


def _error(code: str, status_code: int, **extra):
    return jsonify({"error": code, **extra}), status_code


def _invalid(fields: list[str]):
    return _error("invalid", 400, fields=fields)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _manage():
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    return jsonify(build_manage(runtime, load_manage_context(runtime)))


def _service_detail(service_id: str):
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    detail = build_service_detail(runtime, load_manage_context(runtime), service_id, _now())
    return jsonify(detail) if detail is not None else _error("unknown_service", 404)


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_SERVICE_UPDATE)
def _update_service(service_id: str):
    """서비스 덮어쓰기: 검증 > 대상 확인 > 인프라 잠금 칸 > 외부 점검 상한 > 저장 (null = 원본으로)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    changes, invalid_fields = parse_patch(request.get_json(silent=True), SERVICE_PATCH_VALIDATORS)
    if invalid_fields:
        return _invalid(invalid_fields)
    context = load_manage_context(runtime)
    service = context.effective.service_by_id(service_id)
    if not context.is_known_service(service_id) or service is None:
        return _error("unknown_service", 404)
    if service.project_id is None:
        locked_fields = [name for name in INFRASTRUCTURE_LOCKED_FIELDS if name in changes]
        if locked_fields:
            return _invalid(locked_fields)

    # 바꾼 뒤 실효 등록 정보로 외부 점검 상한 확인 (재추적·주소 추가로 넘칠 수 있음)
    current_override = context.overrides.service_overrides.get(service_id) or ServiceOverride(service_id)
    candidate_overrides = replace(context.overrides, service_overrides={
        **context.overrides.service_overrides, service_id: replace(current_override, **changes)})
    used_count = count_external_checks(merge_overrides(context.file_registry, candidate_overrides))
    if used_count > max(MAX_EXTERNAL_CHECKS, count_external_checks(context.effective)):
        return _error("external_check_limit", 409, maximum=MAX_EXTERNAL_CHECKS)

    runtime.store.save_service_override(service_id, changes, _now())
    set_audit_detail({"service_id": service_id, "changes": changes})
    return jsonify({"ok": True})


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_SERVICE_CREATE)
def _create_service():
    """사용자 추가 서비스: 검증 > 프로젝트 확인 > id 중복 > 외부 점검 상한 > 저장"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    values, invalid_fields = parse_new_service(request.get_json(silent=True))
    if invalid_fields:
        return _invalid(invalid_fields)
    context = load_manage_context(runtime)
    if not context.is_known_project(values["project_id"]):
        return _error("unknown_project", 404)
    if context.is_known_service(values["id"]) or context.effective.service_by_id(values["id"]) is not None:
        return _error("duplicate_id", 409)
    is_tracked = values["status"] != SERVICE_STATUS_RETIRED
    if is_tracked and count_external_checks(context.effective) >= MAX_EXTERNAL_CHECKS:
        return _error("external_check_limit", 409, maximum=MAX_EXTERNAL_CHECKS)

    runtime.store.insert_custom_service(CustomService(**values), _now())
    set_audit_detail({"service_id": values["id"], "project_id": values["project_id"],
                      "external_url": values["external_url"]})
    return jsonify({"ok": True, "id": values["id"]}), 201


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_SERVICE_DELETE)
def _delete_service(service_id: str):
    """사용자 추가 서비스만 삭제 (등록 파일 서비스 409 = retired로만 가능)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    context = load_manage_context(runtime)
    if context.is_registry_service(service_id):
        return _error("registry_service", 409)
    if not runtime.store.delete_custom_service(service_id):
        return _error("unknown_service", 404)
    set_audit_detail({"service_id": service_id})
    return jsonify({"ok": True})


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_PROJECT_UPDATE)
def _update_project(project_id: str):
    """프로젝트 덮어쓰기: 검증 > 대상 확인 > 저장 (null = 원본으로)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    changes, invalid_fields = parse_patch(request.get_json(silent=True), PROJECT_PATCH_VALIDATORS)
    if invalid_fields:
        return _invalid(invalid_fields)
    if not load_manage_context(runtime).is_known_project(project_id):
        return _error("unknown_project", 404)
    runtime.store.save_project_override(project_id, changes, _now())
    set_audit_detail({"project_id": project_id, "changes": changes})
    return jsonify({"ok": True})


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_PROJECT_CREATE)
def _create_project():
    """사용자 추가 프로젝트: 검증 > id 중복 > 저장"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    values, invalid_fields = parse_new_project(request.get_json(silent=True))
    if invalid_fields:
        return _invalid(invalid_fields)
    context = load_manage_context(runtime)
    is_custom_project = any(project.id == values["id"] for project in context.overrides.custom_projects)
    if context.is_known_project(values["id"]) or is_custom_project:
        return _error("duplicate_id", 409)
    runtime.store.insert_custom_project(CustomProject(**values), _now())
    set_audit_detail({"project_id": values["id"]})
    return jsonify({"ok": True, "id": values["id"]}), 201


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_STATUS_PAGE_UPDATE)
def _update_status_page():
    """상태 페이지 설정: 검증 > meta 저장 (null = 기본값)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    changes, invalid_fields = parse_patch(request.get_json(silent=True), STATUS_PAGE_PATCH_VALIDATORS)
    if invalid_fields:
        return _invalid(invalid_fields)
    runtime.store.save_status_page(changes)
    set_audit_detail({"changes": changes})
    return jsonify({"ok": True})


def _dns_candidates():
    """Cloudflare DNS 후보: 토큰 확인 > 조회 > 등록된 외부 주소 호스트 제외"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    token = os.environ.get(CLOUDFLARE_API_TOKEN_ENV)
    if not token:
        return _error("cloudflare_not_configured", 503, reason=f"{CLOUDFLARE_API_TOKEN_ENV} is not set")
    zone_name = os.environ.get(CLOUDFLARE_ZONE_NAME_ENV) or DEFAULT_CLOUDFLARE_ZONE_NAME
    excluded_hosts = registered_hosts(load_manage_context(runtime).effective)
    try:
        candidates = fetch_dns_candidates(token, zone_name, excluded_hosts)
    except DnsLookupError as error:
        return _error("dns_lookup_failed", 502, reason=error.reason)
    return jsonify({"zone": zone_name, "candidates": candidates})
