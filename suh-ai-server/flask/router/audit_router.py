"""
감사로그 조회 라우터 — 전용 관리자 페이지(/admin/audit)용 구조화 API
기록은 util/audit_helper.py의 @audited가 담당하고 여기는 조회 전용이다.
"""
import logging

from flask import Blueprint, jsonify, request

from service import audit_service

logger = logging.getLogger(__name__)

audit_bp = Blueprint('audit', __name__)


@audit_bp.route('/audit/logs', methods=['GET'])
def audit_logs():
    """감사로그 구조화 조회 (필터 + 키셋 페이징, 최신순)"""
    try:
        limit = int(request.args.get('limit', 100))
        before_id = request.args.get('before_id')
        before_id = int(before_id) if before_id is not None else None
    except ValueError:
        return jsonify({'error': 'limit/before_id must be integers'}), 400
    success_raw = request.args.get('success')
    success = None
    if success_raw is not None and success_raw != '':
        success = success_raw.lower() in ('1', 'true', 'yes')
    result = audit_service.query_logs(
        category=request.args.get('category') or None,
        action=request.args.get('action') or None,
        success=success,
        search=request.args.get('search') or None,
        limit=limit,
        before_id=before_id,
    )
    return jsonify({'success': True, **result}), 200
