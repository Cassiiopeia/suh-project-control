"""
시스템 리소스 메트릭 API — 대시보드 시스템 리소스 카드가 사용.
수집은 백그라운드 폴러가 하고 여기서는 버퍼 조회만 한다 (요청당 추가 수집 없음).
인증은 기존 API와 동일하게 nginx X-API-Key 계층에서 처리한다.
"""
from flask import Blueprint, jsonify, request

from config.system_config import SYSTEM_METRICS_HISTORY_MAXLEN
from service.system_metrics_service import system_metrics_history, system_metrics_service

system_bp = Blueprint('system', __name__)


@system_bp.route('/system/metrics', methods=['GET'])
def metrics():
    """현재 스냅샷 + 최근 히스토리. limit=0이면 히스토리 생략."""
    try:
        limit = int(request.args.get('limit', 120))
    except ValueError:
        limit = 120
    limit = max(0, min(limit, SYSTEM_METRICS_HISTORY_MAXLEN))
    points = system_metrics_history.history(limit) if limit else []
    latest = system_metrics_history.history(1)
    # 버퍼가 비어 있으면(기동 직후·폴러 없는 dev 모드) 1회 즉시 수집
    current = latest[-1] if latest else system_metrics_service.collect_snapshot()
    return jsonify({'current': current, 'history': points}), 200
