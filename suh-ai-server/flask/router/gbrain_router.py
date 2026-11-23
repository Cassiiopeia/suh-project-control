"""
gbrain HTTP 서버(MCP) 관리 API: 관리 페이지 /admin/gbrain 과 nginx 게이트가 사용
상태 변경(제어·관리자 로그인)은 감사 기록, 1회용 로그인 경로·게이트 쿠키는 기록하지 않음
"""
import logging

from flask import Blueprint, jsonify, request

from config.gbrain_server_config import (
    GBRAIN_ADMIN_GATE_COOKIE_NAME, GBRAIN_LOG_DEFAULT_LINES,
)
from service import gbrain_server_service as gbrain_server_module
from service.audit_service import AuditAction, AuditCategory
from service.gbrain_server_service import GbrainServerError
from util.audit_helper import audited, set_audit_action

logger = logging.getLogger(__name__)

gbrain_bp = Blueprint('gbrain', __name__)

# 제어 행위 > (감사 행위, 성공 문구, 서비스 호출 메서드 이름)
CONTROL_ACTIONS = {
    'start': (AuditAction.GBRAIN_START, 'gbrain 서버를 시작했어요', 'start_service'),
    'stop': (AuditAction.GBRAIN_STOP, 'gbrain 서버를 중지했어요', 'stop_service'),
    'restart': (AuditAction.GBRAIN_RESTART, 'gbrain 서버를 재시작했어요', 'restart_service'),
}


def _service():
    # 테스트에서 monkeypatch 로 교체할 수 있도록 매 호출 시 모듈 속성을 읽음
    return gbrain_server_module.gbrain_server_service


def _error_response(error: GbrainServerError):
    # 401 은 프론트 apiFetch 가 관리자 키 모달로 처리 > gbrain 쪽 인증 문제는 502·503 으로 구분
    return jsonify({'success': False, 'error': str(error), 'code': error.code}), error.status_code


@gbrain_bp.route('/gbrain/status', methods=['GET'])
def get_status():
    """서비스 상태·헬스·버전·DB·임베딩 (비번 제외)"""
    try:
        return jsonify({'success': True, **_service().get_status()}), 200
    except Exception as error:
        logger.error(f'[gbrain status] failed 500 : {type(error).__name__}')
        return jsonify({'success': False, 'error': 'gbrain 상태를 확인하지 못했어요', 'code': 'status_failed'}), 500


@gbrain_bp.route('/gbrain/logs', methods=['GET'])
def get_logs():
    try:
        lines = int(request.args.get('lines', GBRAIN_LOG_DEFAULT_LINES))
    except ValueError:
        return jsonify({'success': False, 'error': 'lines 는 정수로 보내 주세요', 'code': 'invalid_lines'}), 400
    try:
        return jsonify({'success': True, 'logs': _service().read_logs(lines)}), 200
    except GbrainServerError as error:
        return _error_response(error)


@gbrain_bp.route('/gbrain/control/<action>', methods=['POST'])
@audited(AuditCategory.GBRAIN)
def control_service(action):
    if action not in CONTROL_ACTIONS:
        return jsonify({'success': False, 'error': '지원하는 제어는 start, stop, restart 예요', 'code': 'invalid_action'}), 400
    audit_action, summary, method_name = CONTROL_ACTIONS[action]
    set_audit_action(audit_action)
    if not getattr(_service(), method_name)():
        return jsonify({'success': False, 'error': f'gbrain 서버 {action} 을 끝내지 못했어요 (서버 로그를 확인해 주세요)',
                        'code': 'control_failed'}), 500
    return jsonify({'success': True, 'summary': summary}), 200


@gbrain_bp.route('/gbrain/admin-login', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_ADMIN_LOGIN)
def create_admin_login():
    """1회용 로그인 경로 발급 + 게이트 쿠키 설정 > 프론트가 그 경로로 이동"""
    try:
        admin_login = _service().create_admin_login()
    except GbrainServerError as error:
        return _error_response(error)
    response = jsonify({'success': True, 'login_path': admin_login['login_path']})
    # Path=/ : 게이트가 /admin/* 와 /.well-known/gbrain 둘 다 지킴
    response.set_cookie(GBRAIN_ADMIN_GATE_COOKIE_NAME, admin_login['gate_cookie_value'],
                        max_age=admin_login['gate_valid_seconds'], path='/',
                        secure=True, httponly=True, samesite='Strict')
    return response, 200


@gbrain_bp.route('/gbrain/admin-gate', methods=['GET'])
def check_admin_gate():
    """nginx auth_request 전용: 게이트 쿠키 유효 204, 아니면 401"""
    cookie_value = request.cookies.get(GBRAIN_ADMIN_GATE_COOKIE_NAME)
    if _service().is_admin_gate_valid(cookie_value):
        return '', 204
    return '', 401
