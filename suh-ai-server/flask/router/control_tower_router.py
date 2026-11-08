"""관제소 이벤트 입구: POST /control/events (프로젝트별 토큰 인증, nginx 키 검사 제외 경로)
검증 순서 4단계: 본문 형태 > 토큰 > 프로젝트 등록 > 필드 검증·접수
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from router.control_tower_admin_api import register_admin_api
from router.control_tower_app_attention_api import register_app_attention_api
from router.control_tower_app_attention_intake import register_app_attention_intake
from router.control_tower_icon_api import register_icon_api
from router.control_tower_invite_api import register_invite_api
from router.control_tower_manage_api import register_manage_api
from service.control_tower.app_attention_tokens import event_token_env_name, is_presented_token_valid
from service.control_tower.runtime import get_runtime

control_tower_bp = Blueprint('control_tower', __name__)
register_admin_api(control_tower_bp)  # 관리자 화면 API (nginx 키 검사 대상)
register_manage_api(control_tower_bp)  # 서비스 관리 API (nginx 키 검사 대상)
register_invite_api(control_tower_bp)  # 프로젝트 초대 API (nginx 키 검사 대상)
register_icon_api(control_tower_bp)  # 프로젝트 썸네일 API (nginx 키 검사 대상)
register_app_attention_api(control_tower_bp)  # 앱 확인할 일 관리 API (nginx 키 검사 대상)
register_app_attention_intake(control_tower_bp)  # 앱 확인할 일 push 입구 (nginx 키 검사 제외, 프로젝트 토큰)

TOKEN_HEADER_NAME = 'X-Control-Token'


@control_tower_bp.route('/control/events', methods=['POST'])
def receive_event():
    """앱 이벤트 접수: 런타임 확인 > 본문 형태 > 토큰 > 프로젝트 > 접수"""
    runtime = get_runtime()
    if runtime is None:
        return jsonify({'error': 'unavailable'}), 503

    payload = request.get_json(silent=True)
    project_id = payload.get('project') if isinstance(payload, dict) else None
    if not isinstance(project_id, str):
        return jsonify({'error': 'invalid', 'fields': ['project']}), 400

    if not _is_token_valid(project_id, request.headers.get(TOKEN_HEADER_NAME, '')):
        return jsonify({'error': 'unauthorized'}), 401

    if project_id not in {project.id for project in runtime.registry_provider().projects}:
        return jsonify({'error': 'unknown_project'}), 404

    status_code, body = runtime.dispatcher.accept_event(project_id, payload, datetime.now(timezone.utc))
    return jsonify(body), status_code


def _is_token_valid(project_id: str, presented_token: str) -> bool:
    """토큰 env(현재·_PREVIOUS) 둘 다 없음 > 거부, 있으면 상수 시간 비교"""
    return is_presented_token_valid(event_token_env_name(project_id), presented_token)
