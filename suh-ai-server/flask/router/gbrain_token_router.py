"""
gbrain MCP 기기 토큰 관리 API (#207): 관리 페이지 /admin/gbrain 이 사용
nginx /api/flask/ X-API-Key 뒤에서만 동작, 발급·폐기는 감사 기록 (이름·id·권한·브레인만, 원문 없음)
모든 응답 Cache-Control: no-store (발급 응답에 원문이 실림)
브레인 선택 (#210): ?brain= / 본문 brain (없거나 personal = 개인 브레인, 그 외 팀 프로젝트 키)
"""
from flask import Blueprint, jsonify, request

from router import gbrain_team_router
from service import gbrain_token_service as gbrain_token_module
from service.audit_service import AuditAction, AuditCategory
from service.gbrain_instance import PERSONAL_BRAIN_ID, build_personal_instance
from service.gbrain_server_service import GbrainServerError
from util.audit_helper import audited, set_audit_detail

gbrain_token_bp = Blueprint('gbrain_token', __name__)


def _service():
    # 테스트에서 monkeypatch 로 교체할 수 있도록 매 호출 시 모듈 속성을 읽음
    return gbrain_token_module.gbrain_token_service


def _resolve_brain(brain_id):
    """브레인 id > (GbrainInstance, 토큰 서비스): 개인은 모듈 단일 객체, 팀은 등록부에서 (없으면 404)"""
    if not brain_id or brain_id == PERSONAL_BRAIN_ID:
        return build_personal_instance(), _service()
    instance = gbrain_team_router._service().find_instance(brain_id)
    return instance, gbrain_token_module.get_token_service_for(instance)


def _brain_fields(instance) -> dict:
    """연결 안내에 쓰는 값: 공개 주소, MCP 서버 이름(개인 gbrain / 팀 gbrain-<project>), 기본 권한"""
    return {'brain': instance.brain_id, 'mcp_url': instance.mcp_url, 'mcp_server_name': instance.mcp_server_name,
            'default_scope_preset': instance.default_scope_preset, 'is_team': instance.is_team}


def _no_store(response, status_code):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response, status_code


def _error_response(error: GbrainServerError):
    return _no_store(jsonify({'success': False, 'error': str(error), 'code': error.code}), error.status_code)


@gbrain_token_bp.route('/gbrain/tokens', methods=['GET'])
def list_tokens():
    """토큰 목록 (원문 없음) + 기기에 넣을 공개 MCP 주소·MCP 서버 이름"""
    try:
        instance, token_service = _resolve_brain(request.args.get('brain'))
        tokens = token_service.list_tokens()
    except GbrainServerError as error:
        return _error_response(error)
    return _no_store(jsonify({'success': True, 'tokens': tokens, **_brain_fields(instance)}), 200)


@gbrain_token_bp.route('/gbrain/tokens', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_TOKEN_CREATE)
def create_token():
    """기기 토큰 발급: 원문은 이 응답에만 (감사·로그 제외)"""
    body = request.get_json(silent=True) or {}
    device_name = body.get('name')
    brain_id = body.get('brain') or PERSONAL_BRAIN_ID
    # 실패 시도도 이름·권한·브레인으로 남김 (원문은 아직 없음)
    set_audit_detail({'name': str(device_name)[:64], 'brain': str(brain_id)[:32]})
    try:
        instance, token_service = _resolve_brain(brain_id)
        # 권한 기본값: 팀 브레인 읽기 전용, 개인 읽기+쓰기
        scope_preset = body.get('scope_preset') or instance.default_scope_preset
        set_audit_detail({'scope_preset': str(scope_preset)[:16]})
        created = token_service.create_token(device_name, scope_preset)
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'token_id': created['token']['id'], 'scopes': created['token']['scopes']})
    return _no_store(jsonify({'success': True, 'token': created['token'], 'secret': created['secret'],
                              **_brain_fields(instance)}), 200)


@gbrain_token_bp.route('/gbrain/tokens/<token_id>/revoke', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_TOKEN_REVOKE)
def revoke_token(token_id):
    """토큰 1개 폐기 (id 기준): gbrain 이 다음 요청부터 바로 거부"""
    brain_id = (request.get_json(silent=True) or {}).get('brain') or request.args.get('brain') or PERSONAL_BRAIN_ID
    set_audit_detail({'token_id': token_id[:64], 'brain': str(brain_id)[:32]})
    try:
        _instance, token_service = _resolve_brain(brain_id)
        revoked = token_service.revoke_token(token_id)
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'name': revoked['name'], 'scopes': revoked['scopes']})
    return _no_store(jsonify({'success': True, 'token': revoked}), 200)
