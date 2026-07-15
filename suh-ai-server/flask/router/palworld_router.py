"""
Palworld server management router
"""
from flask import Blueprint, request, jsonify
from service.palworld_service import PalworldService, ServerRunningError
from service.palworld_metrics_history import metrics_history
from service import audit_service
from service.audit_service import AuditCategory, AuditAction
import logging

logger = logging.getLogger(__name__)

palworld_bp = Blueprint('palworld', __name__)
palworld_service = PalworldService()

_CONTROL_AUDIT_ACTIONS = {
    'start': AuditAction.SERVER_START,
    'stop': AuditAction.SERVER_STOP,
    'restart': AuditAction.SERVER_RESTART,
}

_SENSITIVE_SETTING_KEYS = {'ServerPassword', 'AdminPassword'}


def _client_ip() -> str:
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


@palworld_bp.route('/palworld/status', methods=['GET'])
def status():
    """서버 상태 + 접속자 + 메트릭 통합 조회"""
    try:
        return jsonify(palworld_service.get_status()), 200
    except Exception as e:
        logger.error(f"Status error: {str(e)}")
        return jsonify({'error': str(e)}), 500


def _control(action_name):
    try:
        getattr(palworld_service, action_name)()
    except Exception as e:
        logger.error(f"{action_name} error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    audit_action = _CONTROL_AUDIT_ACTIONS.get(action_name)
    if audit_action:
        audit_service.record(AuditCategory.PALWORLD, audit_action, _client_ip())
    return jsonify({'success': True, 'action': action_name}), 200


@palworld_bp.route('/palworld/start', methods=['POST'])
def start():
    """서버 시작"""
    return _control('start')


@palworld_bp.route('/palworld/stop', methods=['POST'])
def stop():
    """서버 중지"""
    return _control('stop')


@palworld_bp.route('/palworld/restart', methods=['POST'])
def restart():
    """서버 재시작"""
    return _control('restart')


@palworld_bp.route('/palworld/settings', methods=['GET'])
def get_settings():
    """PalWorldSettings.ini 조회"""
    try:
        return jsonify(palworld_service.get_settings()), 200
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Settings read error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/settings', methods=['PUT'])
def put_settings():
    """PalWorldSettings.ini 수정 (서버 가동 중이면 409)"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'JSON body required'}), 400
    try:
        before = {}
        try:
            before = palworld_service.get_settings()['settings']
        except Exception:
            pass  # 이전 값 조회 실패는 감사 diff만 비게 할 뿐 수정은 진행
        result = palworld_service.update_settings(data)
        after = result['settings']
        changed = {}
        for key in data:
            if key in after and before.get(key) != after.get(key):
                if key in _SENSITIVE_SETTING_KEYS:
                    changed[key] = {'from': '***', 'to': '***'}
                else:
                    changed[key] = {'from': before.get(key), 'to': after.get(key)}
        if changed:
            audit_service.record(AuditCategory.PALWORLD, AuditAction.SETTINGS_UPDATE,
                                 _client_ip(), {'changed': changed})
        return jsonify(result), 200
    except ServerRunningError as e:
        return jsonify({'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Settings write error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/guide', methods=['GET'])
def guide():
    """게임 접속 가이드 정보 (공개 주소 + ini 실제 설정값)"""
    try:
        return jsonify(palworld_service.get_guide_info()), 200
    except Exception as e:
        logger.error(f"Guide error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/history', methods=['GET'])
def history():
    """메트릭 시계열 히스토리 (FPS·접속자·프레임타임 추이 그래프용)"""
    try:
        limit = int(request.args.get('limit', 120))
    except ValueError:
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 720))
    try:
        return jsonify({'points': metrics_history.history(limit)}), 200
    except Exception as e:
        logger.error(f"History read error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/logs', methods=['GET'])
def logs():
    """서버 로그 tail (source: audit|events|game|stdout|stderr|flask)"""
    try:
        lines = int(request.args.get('lines', 200))
    except ValueError:
        return jsonify({'error': 'lines must be an integer'}), 400
    try:
        source = request.args.get('source', 'game')
        if source == 'audit':
            return jsonify(audit_service.list_logs(lines)), 200
        hide_noise = request.args.get('hide_noise', 'false').lower() in ('1', 'true', 'yes')
        return jsonify(palworld_service.tail_logs(source, lines, hide_noise)), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Log read error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/backups', methods=['GET'])
def list_backups():
    """백업 목록"""
    try:
        return jsonify({'backups': palworld_service.list_backups()}), 200
    except Exception as e:
        logger.error(f"Backup list error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/backups', methods=['POST'])
def create_backup():
    """즉시 백업 실행"""
    try:
        result = palworld_service.create_backup()
        audit_service.record(AuditCategory.PALWORLD, AuditAction.BACKUP_CREATE,
                             _client_ip(), {'name': result.get('name')})
        return jsonify(result), 200
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Backup create error: {str(e)}")
        return jsonify({'error': str(e)}), 500
