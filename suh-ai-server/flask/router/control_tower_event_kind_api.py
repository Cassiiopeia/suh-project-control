"""관제소 프로젝트 알림 종류 API (nginx API 키 보호): 추가 POST·삭제 DELETE /control/projects/<id>/event-kinds
성공 후 백그라운드 디스코드 동기화 1회 (응답은 기다리지 않음, 디스코드 미설정이면 생략), 런타임 미설정 시 503"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from flask import Blueprint, jsonify, request

from service.audit_service import AuditAction, AuditCategory
from service.control_tower.discord_sync import DISCORD_SYNC_LOCK, sync_discord
from service.control_tower.event_kind_validation import parse_new_event_kind
from service.control_tower.manage_view import event_kind_entry, load_manage_context
from service.control_tower.registry import Registry
from service.control_tower.registry_overrides import apply_overrides
from service.control_tower.runtime import get_runtime
from util.audit_helper import audited, set_audit_detail

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
    spec, invalid_fields = parse_new_event_kind(request.get_json(silent=True))
    if invalid_fields:
        return _error("invalid", 400, fields=invalid_fields)
    if not load_manage_context(runtime).is_known_project(project_id):
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
    if not runtime.store.delete_project_event_kind(project_id, kind):
        return _error("unknown_kind", 404)
    set_audit_detail({"project_id": project_id, "kind": kind})
    _schedule_discord_sync(runtime)
    return "", 204


def run_in_background(task: Callable[[], None]) -> None:
    """데몬 스레드 1개로 실행 (테스트에서 동기 실행으로 교체)"""
    threading.Thread(target=task, daemon=True, name=SYNC_THREAD_NAME).start()


def _schedule_discord_sync(runtime) -> None:
    """디스코드 설정(클라이언트·서버 ID) 있을 때만 동기화 1회 예약"""
    discord_client = runtime.discord_client_provider() if runtime.discord_client_provider else None
    if discord_client is None or not runtime.guild_id:
        return
    run_in_background(lambda: _sync_discord_after_change(runtime, discord_client))


def _sync_discord_after_change(runtime, discord_client) -> None:
    """잠금 대기 > 실효 등록 정보 재조립 > 준비 확인 > 동기화 (실패는 기록만)"""
    try:
        with DISCORD_SYNC_LOCK:  # 기동 동기화·관리 화면 버튼과 동시 실행 방지 (끝날 때까지 대기)
            registry = _build_fresh_registry(runtime)
            if not _is_registry_ready(runtime, registry):
                logger.warning("[control-tower event-kind] discord sync skipped : registry is not loaded")
                return
            sync_discord(registry, discord_client, runtime.store, runtime.guild_id)
    except Exception as error:  # 외부 예외 문구는 로그에 싣지 않음
        logger.warning("[control-tower event-kind] discord sync failed : %s", type(error).__name__)


def _build_fresh_registry(runtime) -> Registry:
    """등록 파일 원본 + 지금 저장소 덮어쓰기 (폴러 캐시는 방금 바꾼 종류를 아직 모름)"""
    file_registry_provider = runtime.file_registry_provider or runtime.registry_provider
    return apply_overrides(file_registry_provider(), runtime.store)


def _is_registry_ready(runtime, registry: Registry) -> bool:
    """등록 파일을 한 번이라도 읽음 + 프로젝트 1개 이상 (빈 등록 정보 동기화는 기존 카테고리 전부 보관 처리)"""
    is_file_loaded = runtime.poller is None or runtime.poller.snapshot().registry is not None
    return is_file_loaded and bool(registry.projects)
