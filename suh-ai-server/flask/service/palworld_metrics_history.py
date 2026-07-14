"""
Palworld 메트릭 시계열 히스토리.
PalServer REST /metrics는 순간값만 주므로, 폴러가 주기적으로 스냅샷을 이 버퍼에 적재해
관리자 화면의 FPS·접속자·프레임타임 추이 그래프를 그린다.

- 메모리: 스레드 안전 deque 링버퍼 (maxlen 고정 → 메모리 상한)
- 영속: jsonl append (Flask 재기동 시 최근 스냅샷 복구), 크기 초과 시 1회전
"""
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime

from config.palworld_config import (
    METRICS_HISTORY_FILE, METRICS_HISTORY_MAXLEN, METRICS_HISTORY_MAX_BYTES,
)

logger = logging.getLogger(__name__)

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


class PalworldMetricsHistory:

    def __init__(self, path: str = METRICS_HISTORY_FILE,
                 maxlen: int = METRICS_HISTORY_MAXLEN,
                 max_bytes: int = METRICS_HISTORY_MAX_BYTES):
        self._path = path
        self._max_bytes = max_bytes
        self._buf = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """재기동 시 파일 끝에서 maxlen개까지 복구. 깨진 줄은 건너뛴다."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            for line in lines[-self._buf.maxlen:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._buf.append(json.loads(line))
                except ValueError:
                    continue
        except OSError as e:
            logger.warning(f'metrics history load 실패: {e}')

    def add(self, point: dict):
        """스냅샷 하나를 버퍼에 넣고 파일에 append. 실패해도 예외를 던지지 않는다."""
        with self._lock:
            self._buf.append(point)
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            self._rotate_if_needed()
            with open(self._path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(point, ensure_ascii=False) + '\n')
        except OSError as e:
            logger.warning(f'metrics history append 실패: {e}')

    def add_from_metrics(self, metrics: dict, ts: str = None):
        if metrics:
            self.add(snapshot_from_metrics(metrics, ts))

    def _rotate_if_needed(self):
        if os.path.exists(self._path) and os.path.getsize(self._path) > self._max_bytes:
            rotated = self._path + '.1'
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(self._path, rotated)

    def history(self, limit: int = None) -> list:
        with self._lock:
            points = list(self._buf)
        if limit is not None and limit > 0:
            points = points[-limit:]
        return points


# 폴러(적재)와 라우터(조회)가 공유하는 단일 인스턴스.
# 파일 백업 + 스레드 안전이라 프로세스 전역 공유가 안전하다.
metrics_history = PalworldMetricsHistory()
