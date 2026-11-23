"""
gbrain 팀 브레인 관리 API (#210): 관리 페이지 /admin/gbrain 의 팀 브레인 카드와 관제소 감시가 사용
nginx /api/flask/ X-API-Key 뒤에서 동작 (감시는 127.0.0.1:5000 직접), 만들기·제어는 감사 기록
만들기 응답에 새 쓰기 계정 비번이 실릴 수 있음 > Cache-Control: no-store, 감사 상세에는 이름만
"""
import logging

from flask import Blueprint, jsonify, request

from config.gbrain_server_config import GBRAIN_LOG_DEFAULT_LINES
from router import ai_db_router
from service.audit_service import AuditAction, AuditCategory
from service.gbrain_server_service import GbrainServerError, GbrainServerService
from service.gbrain_team_brain_service import GbrainTeamBrainService
from util.audit_helper import audited, set_audit_action, set_audit_detail

logger = logging.getLogger(__name__)

gbrain_team_bp = Blueprint('gbrain_team', __name__)

# 제어 행위 > (감사 행위, 성공 문구, 서비스 호출 메서드 이름): 개인 브레인과 같은 감사 행위 + 상세 brain
CONTROL_ACTIONS = {
    'start': (AuditAction.GBRAIN_START, '팀 브레인 서버를 시작했어요.', 'start_service'),
    'stop': (AuditAction.GBRAIN_STOP, '팀 브레인 서버를 중지했어요.', 'stop_service'),
    'restart': (AuditAction.GBRAIN_RESTART, '팀 브레인 서버를 재시작했어요.', 'restart_service'),
}


def build_default_service() -> GbrainTeamBrainService:
    # AI 서버 DB 서비스는 요청마다 새로 (ai_db_router 의 시험용 교체 지점을 그대로 따름)
    return GbrainTeamBrainService(ai_db_service_factory=lambda: ai_db_router._service())


# 테스트에서 가짜 서비스를 심는 지점
_service_factory = build_default_service


def set_service_factory(factory) -> None:
    global _service_factory
    _service_factory = factory or build_default_service


def _service() -> GbrainTeamBrainService:
    return _service_factory()


def _no_store(response, status_code):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response, status_code


def _error_response(error: GbrainServerError):
    body = {'success': False, 'error': str(error), 'code': error.code, **(error.details or {})}
    return _no_store(jsonify(body), error.status_code)


@gbrain_team_bp.route('/gbrain/teams', methods=['GET'])
def list_team_brains():
    """팀 브레인 목록 + 상태 (비번 없음)"""
    try:
        return _no_store(jsonify({'success': True, 'brains': _service().list_team_brains()}), 200)
    except GbrainServerError as error:
        return _error_response(error)


@gbrain_team_bp.route('/gbrain/teams/health', methods=['GET'])
def check_team_brains_health():
    """관제소 감시 전용: 전부 정상 200, 하나라도 응답 없음 503 (services.yml gbrain-team-brains)"""
    try:
        health = _service().check_health()
    except GbrainServerError as error:
        return _error_response(error)
    return jsonify({'success': health['is_healthy'], **health}), 200 if health['is_healthy'] else 503


@gbrain_team_bp.route('/gbrain/teams', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_TEAM_CREATE)
def create_team_brain():
    """팀 브레인 만들기 (다시 눌러도 같은 결과), 새 쓰기 계정 비번은 이 응답에만"""
    body = request.get_json(silent=True) or {}
    project = body.get('project')
    writer_password = body.get('writer_password') or None
    set_audit_detail({'project': str(project)[:32], 'has_writer_password': writer_password is not None})
    try:
        created = _service().create_team_brain(project, writer_password)
    except GbrainServerError as error:
        set_audit_detail({'steps': (error.details or {}).get('steps')})
        return _error_response(error)
    set_audit_detail({'steps': created['steps'], 'port': created['brain']['port']})
    return _no_store(jsonify({'success': True, **created}), 200)


@gbrain_team_bp.route('/gbrain/teams/<project>/status', methods=['GET'])
def get_team_brain_status(project):
    try:
        service = _service()
        instance = service.find_instance(project)
        return _no_store(jsonify({'success': True, **service.describe(instance)}), 200)
    except GbrainServerError as error:
        return _error_response(error)


@gbrain_team_bp.route('/gbrain/teams/<project>/logs', methods=['GET'])
def get_team_brain_logs(project):
    try:
        lines = int(request.args.get('lines', GBRAIN_LOG_DEFAULT_LINES))
    except ValueError:
        return jsonify({'success': False, 'error': 'lines 는 정수여야 해요', 'code': 'invalid_lines'}), 400
    try:
        instance = _service().find_instance(project)
        return jsonify({'success': True, 'logs': GbrainServerService.for_instance(instance).read_logs(lines)}), 200
    except GbrainServerError as error:
        return _error_response(error)


@gbrain_team_bp.route('/gbrain/teams/<project>/control/<action>', methods=['POST'])
@audited(AuditCategory.GBRAIN)
def control_team_brain(project, action):
    if action not in CONTROL_ACTIONS:
        return jsonify({'success': False, 'error': '지원하지 않는 제어예요', 'code': 'invalid_action'}), 400
    try:
        instance = _service().find_instance(project)
    except GbrainServerError as error:
        return _error_response(error)
    audit_action, summary, method_name = CONTROL_ACTIONS[action]
    set_audit_action(audit_action)
    set_audit_detail({'brain': instance.brain_id, 'service_name': instance.service_name})
    if not getattr(GbrainServerService.for_instance(instance), method_name)():
        return jsonify({'success': False, 'error': f'팀 브레인 서버 {action} 을 끝내지 못했어요 (서버 로그를 확인해 주세요)',
                        'code': 'control_failed'}), 500
    return jsonify({'success': True, 'summary': summary}), 200
