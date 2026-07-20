"""
Palworld 메트릭 시계열 히스토리.
PalServer REST /metrics는 순간값만 주므로, 폴러가 주기적으로 스냅샷을 버퍼에 적재해
관리자 화면의 FPS·접속자·프레임타임 추이 그래프를 그린다.
저장 구조(링버퍼 + jsonl 회전)는 범용 MetricsHistory를 그대로 쓰고,
여기서는 REST /metrics 응답의 필드 필터만 얹는다.
"""
from datetime import datetime

from config.palworld_config import (
    METRICS_HISTORY_FILE, METRICS_HISTORY_MAXLEN, METRICS_HISTORY_MAX_BYTES,
)
from service.metrics_history import MetricsHistory

# 히스토리에 담을 metrics 필드 (REST /metrics 키 그대로)
_METRIC_KEYS = (
    'currentplayernum', 'serverfps', 'serverfpsaverage',
    'serverframetime', 'days', 'basecampnum', 'uptime', 'maxplayernum',
)


def snapshot_from_metrics(metrics: dict, ts: str = None) -> dict:
    """REST /metrics 응답 dict → 히스토리 포인트 하나. ts 없으면 현재 시각."""
    point = {'ts': ts or datetime.now().isoformat(timespec='seconds')}
    for key in _METRIC_KEYS:
        if key in metrics:
            point[key] = metrics[key]
    return point


class PalworldMetricsHistory(MetricsHistory):

    def __init__(self, path: str = METRICS_HISTORY_FILE,
                 maxlen: int = METRICS_HISTORY_MAXLEN,
                 max_bytes: int = METRICS_HISTORY_MAX_BYTES):
        super().__init__(path, maxlen, max_bytes)

    def add_from_metrics(self, metrics: dict, ts: str = None):
        if metrics:
            self.add(snapshot_from_metrics(metrics, ts))


# 폴러(적재)와 라우터(조회)가 공유하는 단일 인스턴스.
# 파일 백업 + 스레드 안전이라 프로세스 전역 공유가 안전하다.
metrics_history = PalworldMetricsHistory()
