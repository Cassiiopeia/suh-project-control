"""
Claude 로그인 6자리 코드 API: 대기 시작, 상태 조회(코드 포함), 실패 캡처
감사 3종: 요청(새 작업만) / 발급(서비스가 기록) / 열람(작업·IP별 1회)
"""
import os

from flask import Blueprint, jsonify, request, send_file

from service import audit_service
from service import claude_login_code_service as code_service
from service.audit_service import AuditAction, AuditCategory
from util.audit_helper import audited, client_info, set_audit_action, set_audit_detail

claude_login_bp = Blueprint('claude_login', __name__)

# trigger: auto 화면 진입 자동, manual "다시 기다리기" 버튼
ALLOWED_TRIGGERS = ('auto', 'manual')


@claude_login_bp.route('/claude-login/code/request', methods=['POST'])
@audited(AuditCategory.CLAUDE_LOGIN)
def request_code():
    """코드 대기 시작 (진행 중이면 현재 상태)"""
    trigger = (request.get_json(silent=True) or {}).get('trigger')
    if trigger not in ALLOWED_TRIGGERS:
        trigger = 'manual'
    try:
        state, is_new_job = code_service.start_request(trigger, client_info())
    except code_service.NotConfiguredError:
        return jsonify({'error': 'not_configured'}), 400
    if is_new_job:
        set_audit_action(AuditAction.CLAUDE_CODE_REQUEST)
        set_audit_detail({'job_id': state['job_id'], 'trigger': trigger, 'account': state.get('account')})
    # 코드는 열람 감사가 붙는 status 로만 전달
    return jsonify({**state, 'code': None}), 200


@claude_login_bp.route('/claude-login/code/status', methods=['GET'])
def code_status():
    """작업 상태 조회, 코드가 처음 전달되는 클라이언트는 열람 기록"""
    state = code_service.get_state()
    if state.get('code'):
        info = client_info()
        if code_service.should_record_view(state['job_id'], info['client_ip']):
            audit_service.record(
                AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_CODE_VIEW, info['actor_ip'],
                {'job_id': state['job_id'], 'mail_received_at': state.get('mail_received_at')},
                client_ip=info['client_ip'], proxy_chain=info['proxy_chain'],
                user_agent=info['user_agent'])
    return jsonify(state), 200


@claude_login_bp.route('/claude-login/code/screenshot', methods=['GET'])
def failure_screenshot():
    """코드 못 찾은 화면 캡처 (없으면 404)"""
    if not os.path.isfile(code_service.SCREENSHOT_PATH):
        return jsonify({'error': 'screenshot_not_found'}), 404
    return send_file(os.path.abspath(code_service.SCREENSHOT_PATH), mimetype='image/png', max_age=0)
