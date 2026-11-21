"""
gbrain MCP 기기 토큰 관리 API (#207): 관리 페이지 /admin/gbrain 이 사용
nginx /api/flask/ X-API-Key 뒤에서만 동작, 발급·폐기는 감사 기록 (이름·id·권한만, 원문 없음)
모든 응답 Cache-Control: no-store (발급 응답에 원문이 실림)
"""
from flask import Blueprint, jsonify, request

from config.gbrain_server_config import GBRAIN_PUBLIC_MCP_URL
from service import gbrain_token_service as gbrain_token_module
from service.audit_service import AuditAction, AuditCategory
from service.gbrain_server_service import GbrainServerError
from service.gbrain_token_service import DEFAULT_SCOPE_PRESET
from util.audit_helper import audited, set_audit_detail

gbrain_token_bp = Blueprint('gbrain_token', __name__)


def _service():
    # 테스트에서 monkeypatch 로 교체할 수 있도록 매 호출 시 모듈 속성을 읽음
    return gbrain_token_module.gbrain_token_service


def _no_store(response, status_code):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response, status_code


def _error_response(error: GbrainServerError):
    return _no_store(jsonify({'success': False, 'error': str(error), 'code': error.code}), error.status_code)


@gbrain_token_bp.route('/gbrain/tokens', methods=['GET'])
def list_tokens():
    """토큰 목록 (원문 없음) + 기기에 넣을 공개 MCP 주소"""
    try:
        tokens = _service().list_tokens()
    except GbrainServerError as error:
        return _error_response(error)
    return _no_store(jsonify({'success': True, 'tokens': tokens, 'mcp_url': GBRAIN_PUBLIC_MCP_URL}), 200)


@gbrain_token_bp.route('/gbrain/tokens', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_TOKEN_CREATE)
def create_token():
    """기기 토큰 발급: 원문은 이 응답에만 (감사·로그 제외)"""
    body = request.get_json(silent=True) or {}
    device_name = body.get('name')
    scope_preset = body.get('scope_preset', DEFAULT_SCOPE_PRESET)
    # 실패 시도도 이름·권한으로 남김 (원문은 아직 없음)
    set_audit_detail({'name': str(device_name)[:64], 'scope_preset': str(scope_preset)[:16]})
    try:
        created = _service().create_token(device_name, scope_preset)
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'token_id': created['token']['id'], 'scopes': created['token']['scopes']})
    return _no_store(jsonify({'success': True, 'token': created['token'], 'secret': created['secret'],
                              'mcp_url': GBRAIN_PUBLIC_MCP_URL}), 200)


@gbrain_token_bp.route('/gbrain/tokens/<token_id>/revoke', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_TOKEN_REVOKE)
def revoke_token(token_id):
    """토큰 1개 폐기 (id 기준): gbrain 이 다음 요청부터 바로 거부"""
    set_audit_detail({'token_id': token_id[:64]})
    try:
        revoked = _service().revoke_token(token_id)
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'name': revoked['name'], 'scopes': revoked['scopes']})
    return _no_store(jsonify({'success': True, 'token': revoked}), 200)
