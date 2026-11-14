"""관제소 앱 확인할 일 push 입구: POST /control/attention/<project>/<source> (프로젝트 이벤트 토큰, nginx 키 검사 제외 경로)
검증 순서: 크기 413 > JSON 400 > 토큰 401 > 소스 404 > 방식·켜짐 403 > pull과 같은 처리 경로(ingest) 202"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from service.control_tower.app_attention_fetch import FETCH_RESULT_OK, TOKEN_HEADER_NAME, FetchOutcome
from service.control_tower.app_attention_models import MAX_BODY_BYTES, SOURCE_MODE_PULL
from service.control_tower.project_event_tokens import is_project_token_valid
from service.control_tower.runtime import get_runtime

logger = logging.getLogger(__name__)


def register_app_attention_intake(blueprint: Blueprint) -> None:
    """push 입구 1개를 관제소 블루프린트에 등록"""
    blueprint.add_url_rule("/control/attention/<project_id>/<source_id>", "control_app_attention_intake",
                           _receive_snapshot, methods=["POST"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error(code: str, status_code: int):
    return jsonify({"error": code}), status_code


def _receive_snapshot(project_id: str, source_id: str):
    """스냅샷 접수: 런타임 > 크기 > JSON > 토큰 > 소스 > 방식·켜짐 > ingest"""
    runtime = get_runtime()
    if runtime is None or runtime.app_attention_ingest is None:
        return _error("unavailable", 503)

    # 본문 64KB 초과는 해석 전에 거부 (길이 헤더 > 실제로 읽은 크기 순)
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return _error("too_large", 413)
    body = request.stream.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        return _error("too_large", 413)
    try:
        document = json.loads(body)
    except ValueError:  # JSON 문법 오류·잘못된 UTF-8
        return _error("invalid", 400)

    if not is_project_token_valid(runtime.store, project_id, request.headers.get(TOKEN_HEADER_NAME, ""), _now()):
        return _error("unauthorized", 401)
    source = runtime.store.get_attention_source(project_id, source_id)
    if source is None:
        return _error("unknown_source", 404)
    if source.mode == SOURCE_MODE_PULL:
        return _error("push_disabled", 403)
    if not source.is_enabled:
        return _error("source_disabled", 403)

    report = runtime.app_attention_ingest.ingest(source, FetchOutcome(FETCH_RESULT_OK, document, None, None),
                                                 _now())
    logger.info("[control-tower app-attention] push accepted : %s/%s result=%s dropped=%d",
                project_id, source_id, report.result, len(report.dropped_items))
    return jsonify({"result": report.result,
                    "dropped_items": [{"key": key, "reason": reason} for key, reason in report.dropped_items]}), 202
