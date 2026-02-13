"""
Log viewer router - 외부에서 서버 로그를 확인하는 API
"""
import os
from flask import Blueprint, request, jsonify
import logging

logger = logging.getLogger(__name__)

log_bp = Blueprint('log', __name__)

# 로그 파일 경로
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'nssm-stderr.log')


@log_bp.route('/logs', methods=['GET'])
def get_logs():
    """
    서버 로그 조회

    Query Parameters:
    - lines: 최근 N줄 (기본값: 50, 최대: 500)
    - level: 로그 레벨 필터 (INFO, ERROR, WARNING 등)
    - search: 키워드 검색

    Response:
    {
        "success": true,
        "total_lines": 50,
        "log_file": "nssm-stderr.log",
        "logs": ["line1", "line2", ...]
    }
    """
    try:
        # 파라미터 파싱
        lines = min(int(request.args.get('lines', 50)), 500)
        level_filter = request.args.get('level', '').upper()
        search_keyword = request.args.get('search', '').strip()

        if not os.path.exists(LOG_FILE):
            return jsonify({
                'success': False,
                'error': 'Log file not found',
                'log_file': LOG_FILE
            }), 404

        # 파일 읽기 (마지막 N줄)
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()

        # 필터 적용
        filtered_lines = all_lines
        if level_filter:
            filtered_lines = [l for l in filtered_lines if f'[{level_filter}]' in l]
        if search_keyword:
            filtered_lines = [l for l in filtered_lines if search_keyword.lower() in l.lower()]

        # 최근 N줄만
        recent_lines = [l.rstrip('\n\r') for l in filtered_lines[-lines:]]

        return jsonify({
            'success': True,
            'total_lines': len(recent_lines),
            'total_log_lines': len(all_lines),
            'log_file': 'nssm-stderr.log',
            'filters': {
                'lines': lines,
                'level': level_filter or None,
                'search': search_keyword or None
            },
            'logs': recent_lines
        }), 200

    except Exception as e:
        logger.error(f"Log read error: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to read logs: {str(e)}'}), 500


@log_bp.route('/logs/stream', methods=['GET'])
def get_logs_stream():
    """
    서버 로그 스트림 (최근 로그를 텍스트로 반환 - 브라우저에서 바로 보기 편함)

    Query Parameters:
    - lines: 최근 N줄 (기본값: 100, 최대: 500)
    """
    try:
        lines = min(int(request.args.get('lines', 100)), 500)

        if not os.path.exists(LOG_FILE):
            return "Log file not found", 404

        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()

        recent_lines = all_lines[-lines:]
        text_output = ''.join(recent_lines)

        return text_output, 200, {'Content-Type': 'text/plain; charset=utf-8'}

    except Exception as e:
        return f"Error: {str(e)}", 500
