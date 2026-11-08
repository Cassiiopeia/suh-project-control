"""관제소 프로젝트 썸네일 API (nginx API 키 보호): 업로드·주소 가져오기·삭제
저장은 로컬 DB뿐 > 다음 폴러 틱(60초 안)에 스냅샷 버전이 바뀌어 Worker로 전달됨, 런타임 미설정 시 503"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from service.audit_service import AuditAction, AuditCategory
from service.control_tower.manage_view import load_manage_context
from service.control_tower.override_validation import parse_icon_request
from service.control_tower.project_icon_service import (
    ProjectIconError, decode_base64_image, fetch_icon_bytes, normalize_icon,
)
from service.control_tower.runtime import get_runtime
from util.audit_helper import audited, set_audit_detail

# 오류 코드 > HTTP 상태 (이미지 문제 400, 크기 413, 외부 주소 가져오기 실패 502)
ICON_ERROR_STATUS_CODES = {"invalid_image": 400, "image_too_large": 413, "icon_fetch_failed": 502}


def register_icon_api(blueprint: Blueprint) -> None:
    """썸네일 API 2개를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/projects/<project_id>/icon", "control_project_icon_update",
                           _update_icon, methods=["PUT"])
    blueprint.add_url_rule("/control/projects/<project_id>/icon", "control_project_icon_delete",
                           _delete_icon, methods=["DELETE"])


def _error(code: str, status_code: int, **extra):
    return jsonify({"error": code, **extra}), status_code


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_PROJECT_ICON_UPDATE)
def _update_icon(project_id: str):
    """썸네일 저장: 검증 > 프로젝트 확인 > (업로드 해독 | 주소 가져오기) > 128px WebP 정규화 > 저장"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    values, invalid_fields = parse_icon_request(request.get_json(silent=True))
    if invalid_fields:
        return _error("invalid", 400, fields=invalid_fields)
    if not load_manage_context(runtime).is_known_project(project_id):
        return _error("unknown_project", 404)
    try:
        raw_bytes = decode_base64_image(values["image_base64"]) if "image_base64" in values \
            else fetch_icon_bytes(values["source_url"])
        image_webp, content_hash = normalize_icon(raw_bytes)
    except ProjectIconError as error:
        return _error(error.code, ICON_ERROR_STATUS_CODES.get(error.code, 400))
    runtime.store.save_project_icon(project_id, image_webp, content_hash, datetime.now(timezone.utc))
    # 주소 가져오기는 주소 기록 (이미지 본문은 기록하지 않음)
    set_audit_detail({"project_id": project_id, "source": "url" if "source_url" in values else "upload",
                      "source_url": values.get("source_url"), "content_hash": content_hash})
    return jsonify({"ok": True, "content_hash": content_hash})


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_PROJECT_ICON_DELETE)
def _delete_icon(project_id: str):
    """썸네일 삭제: 프로젝트 확인 > 삭제 (없으면 404, 삭제해도 등록 파일 기본 이미지는 다시 가져오지 않음)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    if not load_manage_context(runtime).is_known_project(project_id):
        return _error("unknown_project", 404)
    if not runtime.store.delete_project_icon(project_id):
        return _error("no_icon", 404)
    set_audit_detail({"project_id": project_id})
    return jsonify({"ok": True})
