"""
Claude 로그인 API: Gmail 계정 관리(목록·추가·수정·삭제·접속 테스트), 계정별 코드 대기·상태·실패 캡처
감사: 계정 변경 4종 / 코드 요청(새 작업만) / 발급(서비스가 기록) / 열람(작업·IP별 1회)
"""
import os

from flask import Blueprint, jsonify, request, send_file

from config import claude_login_config as config
from service import audit_service
from service import claude_login_account_service as account_service
from service import claude_login_code_service as code_service
from service.audit_service import AuditAction, AuditCategory
from service.claude_login_account_repository import AccountStoreUnavailableError, DuplicateAccountError
from util.audit_helper import audited, client_info, set_audit_action, set_audit_detail

claude_login_bp = Blueprint('claude_login', __name__)

# trigger: auto 화면 진입 자동, manual "다시 기다리기" 버튼
ALLOWED_TRIGGERS = ('auto', 'manual')
# 서비스 예외 > (HTTP 상태, error 코드) — 화면 문구는 claude-login.js ERROR_LABELS
ERROR_RESPONSES = {
    account_service.SecretNotConfiguredError: (400, 'secret_not_configured'),
    account_service.AccountLoginFailedError: (400, 'imap_login_failed'),
    account_service.AccountNotFoundError: (404, 'account_not_found'),
    DuplicateAccountError: (409, 'duplicate_account'),
    AccountStoreUnavailableError: (503, 'store_unavailable'),
}


@claude_login_bp.errorhandler(account_service.AccountValidationError)
def handle_validation_error(error):
    return jsonify({'error': error.reason}), 400


def _register_error_responses():
    """ERROR_RESPONSES 예외 > JSON 오류 응답 (감사 데코레이터가 실패 기록 후 다시 던진 예외 포함)"""
    for exception_type, (status, error_code) in ERROR_RESPONSES.items():
        def handler(_error, status=status, error_code=error_code):
            return jsonify({'error': error_code}), status
        claude_login_bp.register_error_handler(exception_type, handler)


_register_error_responses()


# 계정 관리 API

@claude_login_bp.route('/claude-login/accounts', methods=['GET'])
def list_accounts():
    """계정 목록 (앱 비밀번호 제외)"""
    return jsonify({'accounts': account_service.list_accounts(),
                    'is_secret_configured': config.is_secret_configured()}), 200


@claude_login_bp.route('/claude-login/accounts', methods=['POST'])
@audited(AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_ACCOUNT_CREATE)
def create_account():
    """접속 테스트 성공 시 암호화 저장"""
    body = request.get_json(silent=True) or {}
    set_audit_detail({'gmail_address': body.get('gmail_address')})
    account = account_service.create_account(
        body.get('display_name'), body.get('gmail_address'), body.get('app_password'))
    set_audit_detail({'account_id': account['id'], 'gmail_address': account['gmail_address']})
    return jsonify(account), 201


@claude_login_bp.route('/claude-login/accounts/<int:account_id>', methods=['PUT'])
@audited(AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_ACCOUNT_UPDATE)
def update_account(account_id):
    """이름·사용 여부·앱 비밀번호 중 전달된 항목만 수정"""
    body = request.get_json(silent=True) or {}
    set_audit_detail({'account_id': account_id,
                      'changed_fields': sorted(key for key in ('display_name', 'is_enabled', 'app_password')
                                               if body.get(key) is not None)})
    account = account_service.update_account(
        account_id, display_name=body.get('display_name'), is_enabled=body.get('is_enabled'),
        app_password=body.get('app_password'))
    set_audit_detail({'gmail_address': account['gmail_address']})
    return jsonify(account), 200


@claude_login_bp.route('/claude-login/accounts/<int:account_id>', methods=['DELETE'])
@audited(AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_ACCOUNT_DELETE)
def delete_account(account_id):
    set_audit_detail({'account_id': account_id})
    account = account_service.delete_account(account_id)
    set_audit_detail({'gmail_address': account['gmail_address']})
    return jsonify(account), 200


@claude_login_bp.route('/claude-login/accounts/<int:account_id>/test', methods=['POST'])
@audited(AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_ACCOUNT_TEST)
def test_account(account_id):
    """저장된 앱 비밀번호로 Gmail 접속 테스트 (실패도 200 + is_success false)"""
    set_audit_detail({'account_id': account_id})
    result = account_service.verify_saved_account(account_id)
    set_audit_detail({'gmail_address': result['account']['gmail_address'], 'is_success': result['is_success']})
    return jsonify(result), 200


# 코드 대기 API

@claude_login_bp.route('/claude-login/code/request', methods=['POST'])
@audited(AuditCategory.CLAUDE_LOGIN)
def request_code():
    """대기 시작 (account_id 없으면 사용 중 계정 전체, 진행 중 계정은 현재 상태)"""
    body = request.get_json(silent=True) or {}
    trigger = body.get('trigger') if body.get('trigger') in ALLOWED_TRIGGERS else 'manual'
    account_id = body.get('account_id')
    if account_id is not None and not isinstance(account_id, int):
        return jsonify({'error': 'invalid_account_id'}), 400
    results = code_service.start_requests(trigger, client_info(), account_id)
    new_job_states = [state for state, is_new_job in results if is_new_job]
    if new_job_states:
        set_audit_action(AuditAction.CLAUDE_CODE_REQUEST)
        set_audit_detail({'trigger': trigger,
                          'jobs': [{'account_id': state['account_id'], 'job_id': state['job_id']}
                                   for state in new_job_states]})
    # 코드는 열람 감사가 붙는 status 로만 전달
    return jsonify({'accounts': [{**state, 'code': None} for state, _ in results]}), 200


@claude_login_bp.route('/claude-login/code/status', methods=['GET'])
def code_status():
    """계정별 작업 상태, 코드가 처음 전달되는 클라이언트는 계정별 열람 기록"""
    states = code_service.get_states()
    info = client_info()
    for state in states:
        if state.get('code') and code_service.should_record_view(state['job_id'], info['client_ip']):
            audit_service.record(
                AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_CODE_VIEW, info['actor_ip'],
                {'job_id': state['job_id'], 'account_id': state['account_id'],
                 'mail_received_at': state.get('mail_received_at')},
                client_ip=info['client_ip'], proxy_chain=info['proxy_chain'],
                user_agent=info['user_agent'])
    return jsonify({'accounts': states, 'is_secret_configured': config.is_secret_configured()}), 200


@claude_login_bp.route('/claude-login/code/screenshot', methods=['GET'])
def failure_screenshot():
    """계정별 코드 못 찾은 화면 캡처 (없으면 404)"""
    account_id = request.args.get('account_id', type=int)
    if account_id is None:
        return jsonify({'error': 'invalid_account_id'}), 400
    path = code_service.screenshot_path(account_id)
    if not os.path.isfile(path):
        return jsonify({'error': 'screenshot_not_found'}), 404
    return send_file(os.path.abspath(path), mimetype='image/png', max_age=0)
