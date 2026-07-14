"""
Palworld server management router
"""
from flask import Blueprint, request, jsonify
from service.palworld_service import PalworldService, ServerRunningError
import logging

logger = logging.getLogger(__name__)

palworld_bp = Blueprint('palworld', __name__)
palworld_service = PalworldService()


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
        return jsonify({'success': True, 'action': action_name}), 200
    except Exception as e:
        logger.error(f"{action_name} error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
        return jsonify(palworld_service.update_settings(data)), 200
    except ServerRunningError as e:
        return jsonify({'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Settings write error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/logs', methods=['GET'])
def logs():
    """서버 로그 tail"""
    try:
        lines = int(request.args.get('lines', 200))
    except ValueError:
        return jsonify({'error': 'lines must be an integer'}), 400
    try:
        source = request.args.get('source', 'game')
        return jsonify(palworld_service.tail_logs(source, lines)), 200
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
        return jsonify(palworld_service.create_backup()), 200
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Backup create error: {str(e)}")
        return jsonify({'error': str(e)}), 500
