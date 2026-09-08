"""
Sunshine(Moonlight 호스트) 제어 API — 관리 페이지 /admin/sunshine 이 사용
상태 변경(POST)은 전부 감사로그에 남긴다. 입력 검증 실패(400)는 감사 대상이 아니다.
"""
import logging
import re

from flask import Blueprint, jsonify, request

from service import sunshine_service as sunshine_module
from service.audit_service import AuditAction, AuditCategory
from service.sunshine_service import SunshineApiError
from util.audit_helper import audited, set_audit_action, set_audit_detail

logger = logging.getLogger(__name__)

sunshine_bp = Blueprint('sunshine', __name__)

PIN_RE = re.compile(r'^\d{4}$')
CLIENT_NAME_MAX = 64
UUID_RE = re.compile(r'^[0-9A-Fa-f-]{8,64}$')

CONTROL_ACTIONS = {
    'start': (AuditAction.SUNSHINE_START, 'Sunshine 서비스를 시작했습니다.'),
    'stop': (AuditAction.SUNSHINE_STOP, 'Sunshine 서비스를 중지했습니다.'),
    'restart': (AuditAction.SUNSHINE_RESTART, 'Sunshine 서비스를 재시작했습니다.'),
}


def _svc():
    # 테스트에서 monkeypatch 로 교체할 수 있도록 매 호출 시 모듈 속성을 읽는다
    return sunshine_module.sunshine_service


def _api_error(e: SunshineApiError):
    # 401 을 그대로 내리면 프론트 apiFetch 가 관리자 API Key 모달을 띄운다.
    # Sunshine 쪽 인증/연결 문제는 게이트웨이 오류(502)로 구분해 내린다.
    return jsonify({'success': False, 'error': str(e), 'code': e.code}), 502


@sunshine_bp.route('/sunshine/status', methods=['GET'])
def get_status():
    """서비스 구동 여부 + 스트림 상태(FREE/BUSY) + 실행 중 앱"""
    try:
        return jsonify({'success': True, **_svc().get_status()}), 200
    except Exception as e:
        logger.error(f'Sunshine status failed: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@sunshine_bp.route('/sunshine/clients', methods=['GET'])
def list_clients():
    try:
        return jsonify({'success': True, 'clients': _svc().list_clients()}), 200
    except SunshineApiError as e:
        return _api_error(e)


@sunshine_bp.route('/sunshine/clients/unpair', methods=['POST'])
@audited(AuditCategory.SUNSHINE)
def unpair_client():
    data = request.get_json(silent=True) or {}
    uuid = str(data.get('uuid', '')).strip()
    if not UUID_RE.match(uuid):
        return jsonify({'success': False, 'error': 'uuid 형식이 올바르지 않습니다'}), 400
    set_audit_action(AuditAction.SUNSHINE_UNPAIR)
    set_audit_detail({'uuid': uuid, 'name': data.get('name')})
    try:
        _svc().unpair_client(uuid)
        return jsonify({'success': True, 'summary': '페어링을 해제했습니다.'}), 200
    except SunshineApiError as e:
        return _api_error(e)


@sunshine_bp.route('/sunshine/pin', methods=['POST'])
@audited(AuditCategory.SUNSHINE)
def submit_pin():
    """Moonlight 가 표시한 PIN 과 기기 이름으로 페어링 승인"""
    data = request.get_json(silent=True) or {}
    pin = str(data.get('pin', '')).strip()
    name = str(data.get('name', '')).strip()
    if not PIN_RE.match(pin):
        return jsonify({'success': False, 'error': 'PIN 은 숫자 4자리여야 합니다'}), 400
    if not name or len(name) > CLIENT_NAME_MAX:
        return jsonify({'success': False, 'error': f'기기 이름은 1~{CLIENT_NAME_MAX}자여야 합니다'}), 400
    set_audit_action(AuditAction.SUNSHINE_PAIR)
    set_audit_detail({'name': name})  # PIN 은 일회성이지만 기록하지 않는다
    try:
        _svc().submit_pin(pin, name)
        return jsonify({'success': True, 'summary': f'"{name}" 페어링을 승인했습니다.'}), 200
    except SunshineApiError as e:
        return _api_error(e)


@sunshine_bp.route('/sunshine/session/close', methods=['POST'])
@audited(AuditCategory.SUNSHINE, AuditAction.SUNSHINE_SESSION_CLOSE)
def close_session():
    """실행 중 앱 종료 — BUSY 로 굳은 세션을 풀 때 사용 (접속 중인 클라이언트는 끊긴다)"""
    try:
        _svc().close_session()
        return jsonify({'success': True, 'summary': '실행 중인 스트리밍 세션을 종료했습니다.'}), 200
    except SunshineApiError as e:
        return _api_error(e)


@sunshine_bp.route('/sunshine/control/<action>', methods=['POST'])
@audited(AuditCategory.SUNSHINE)
def control_service(action):
    if action not in CONTROL_ACTIONS:
        return jsonify({'success': False, 'error': 'Invalid action'}), 400
    audit_action, summary = CONTROL_ACTIONS[action]
    set_audit_action(audit_action)
    svc = _svc()
    ok = {'start': svc.start_service, 'stop': svc.stop_service, 'restart': svc.restart_service}[action]()
    if not ok:
        return jsonify({'success': False, 'error': f'Sunshine 서비스 {action} 실패 (서버 로그 확인)'}), 500
    return jsonify({'success': True, 'summary': summary}), 200


@sunshine_bp.route('/sunshine/logs', methods=['GET'])
def get_logs():
    try:
        lines = int(request.args.get('lines', 200))
    except ValueError:
        return jsonify({'success': False, 'error': 'lines must be an integer'}), 400
    try:
        return jsonify({'success': True, 'logs': _svc().read_logs(lines)}), 200
    except SunshineApiError as e:
        return _api_error(e)
