"""관제소 앱 확인할 일 관리 API (nginx API 키 보호): 현황, 소스 목록·추가·수정·삭제, 연결 확인, 항목·덮어쓰기
소스 저장은 다음 폴러 틱부터 수집에 반영, 연결 확인은 상태·기준선·알림을 바꾸지 않음, 런타임 미설정 시 503"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from service.audit_service import AuditAction, AuditCategory
from service.control_tower.app_attention_fetch import fetch_attention
from service.control_tower.app_attention_source_validation import (
    parse_item_override_patch, parse_new_source, parse_source_patch,
)
from service.control_tower.app_attention_store import AttentionItemOverride, AttentionSource
from service.control_tower.app_attention_view import (
    build_app_attention_board, build_source_entry, build_source_items, build_source_list, override_entry,
)
from service.control_tower.manage_view import load_manage_context
from service.control_tower.runtime import get_runtime
from util.audit_helper import audited, set_audit_detail

SOURCE_PATH = "/control/app-attention/sources/<project_id>/<source_id>"


def register_app_attention_api(blueprint: Blueprint) -> None:
    """관리 API 7개(경로 6개)를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/app-attention", "control_app_attention_board", _board, methods=["GET"])
    blueprint.add_url_rule("/control/app-attention/sources", "control_app_attention_sources", _list_sources,
                           methods=["GET"])
    blueprint.add_url_rule("/control/app-attention/sources", "control_app_attention_source_create",
                           _create_source, methods=["POST"])
    blueprint.add_url_rule(SOURCE_PATH, "control_app_attention_source_update", _update_source, methods=["PATCH"])
    blueprint.add_url_rule(SOURCE_PATH, "control_app_attention_source_delete", _delete_source, methods=["DELETE"])
    blueprint.add_url_rule(SOURCE_PATH + "/test", "control_app_attention_source_test", _test_source,
                           methods=["POST"])
    blueprint.add_url_rule(SOURCE_PATH + "/items", "control_app_attention_source_items", _source_items,
                           methods=["GET"])
    blueprint.add_url_rule("/control/app-attention/items/<project_id>/<source_id>/<path:item_key>",
                           "control_app_attention_item_override", _update_item_override, methods=["PATCH"])


def _error(code: str, status_code: int, **extra):
    return jsonify({"error": code, **extra}), status_code


def _invalid(fields: list[str]):
    return _error("invalid", 400, fields=fields)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _project_name(registry, project_id: str) -> str:
    return next((project.name for project in registry.projects if project.id == project_id), project_id)


def _source_entry(runtime, source: AttentionSource) -> dict:
    state = runtime.store.get_attention_source_state(source.project_id, source.source_id)
    return build_source_entry(runtime.store, source, state,
                              _project_name(load_manage_context(runtime).effective, source.project_id))


def _board():
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    return jsonify(build_app_attention_board(runtime.store, load_manage_context(runtime).effective))


def _list_sources():
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    return jsonify(build_source_list(runtime.store, load_manage_context(runtime).effective))


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_APP_ATTENTION_SOURCE_SAVE)
def _create_source():
    """소스 추가: 검증 > 프로젝트 확인(등록 파일 + 관리 화면 추가) > 중복 > 저장"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    values, invalid_fields = parse_new_source(request.get_json(silent=True))
    if invalid_fields:
        return _invalid(invalid_fields)
    if not load_manage_context(runtime).is_known_project(values["project_id"]):
        return _error("unknown_project", 404)
    if runtime.store.get_attention_source(values["project_id"], values["source_id"]) is not None:
        return _error("source_exists", 409)

    now = _now()
    source = AttentionSource(**{**values, "url": values["url"] or ""}, created_at=now, updated_at=now)
    runtime.store.save_attention_source(source)
    set_audit_detail({"project_id": source.project_id, "source_id": source.source_id, "url": source.url,
                      "mode": source.mode})
    return jsonify({"ok": True, "source": _source_entry(runtime, source)}), 201


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_APP_ATTENTION_SOURCE_SAVE)
def _update_source(project_id: str, source_id: str):
    """소스 수정: 대상 확인 > 기존 값과 합쳐 검증 > 저장 (project_id·source_id는 바꿀 수 없음)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    existing = runtime.store.get_attention_source(project_id, source_id)
    if existing is None:
        return _error("unknown_source", 404)
    payload = request.get_json(silent=True)
    values, invalid_fields = parse_source_patch(payload, existing)
    if invalid_fields:
        return _invalid(invalid_fields)

    source = replace(existing, **{**values, "url": values["url"] or ""}, updated_at=_now())
    runtime.store.save_attention_source(source)
    set_audit_detail({"project_id": project_id, "source_id": source_id, "changes": payload})
    return jsonify({"ok": True, "source": _source_entry(runtime, source)})


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_APP_ATTENTION_SOURCE_DELETE)
def _delete_source(project_id: str, source_id: str):
    """소스 삭제: 상태·항목·덮어쓰기·알림 기준·이력 함께 삭제 (없으면 404)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    if not runtime.store.delete_attention_source(project_id, source_id):
        return _error("unknown_source", 404)
    set_audit_detail({"project_id": project_id, "source_id": source_id})
    return jsonify({"ok": True})


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_APP_ATTENTION_SOURCE_TEST)
def _test_source(project_id: str, source_id: str):
    """연결 확인: 즉시 1회 수집(etag 없이) > 검증 결과·항목 미리보기 (저장·발송 없음)"""
    runtime = get_runtime()
    if runtime is None or runtime.app_attention_ingest is None:
        return _error("unavailable", 503)
    source = runtime.store.get_attention_source(project_id, source_id)
    if source is None:
        return _error("unknown_source", 404)
    preview = runtime.app_attention_ingest.preview(source, fetch_attention(source, None))
    set_audit_detail({"project_id": project_id, "source_id": source_id, "result": preview["result"],
                      "error_label": preview["error_label"]})
    return jsonify(preview)


def _source_items(project_id: str, source_id: str):
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    source = runtime.store.get_attention_source(project_id, source_id)
    if source is None:
        return _error("unknown_source", 404)
    return jsonify(build_source_items(runtime.store, source, _source_entry(runtime, source)))


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_APP_ATTENTION_ITEM_OVERRIDE)
def _update_item_override(project_id: str, source_id: str, item_key: str):
    """항목 덮어쓰기: 검증 > 소스·항목 확인 > 기존 덮어쓰기에 합쳐 저장 (null = 앱 값·기본 규칙)"""
    runtime = get_runtime()
    if runtime is None:
        return _error("unavailable", 503)
    changes, invalid_fields = parse_item_override_patch(request.get_json(silent=True))
    if invalid_fields:
        return _invalid(invalid_fields)
    if runtime.store.get_attention_source(project_id, source_id) is None:
        return _error("unknown_source", 404)
    if item_key not in runtime.store.load_attention_items(project_id, source_id):
        return _error("unknown_item", 404)

    current = runtime.store.load_attention_overrides(project_id, source_id).get(item_key) \
        or AttentionItemOverride(project_id, source_id, item_key)
    override = replace(current, **changes)
    runtime.store.save_attention_override(override)
    set_audit_detail({"project_id": project_id, "source_id": source_id, "key": item_key, "changes": changes})
    return jsonify({"ok": True, "override": override_entry(override)})
