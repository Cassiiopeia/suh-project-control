"""
범용 메트릭 시계열 히스토리 (링버퍼 + jsonl 영속).
팰월드 메트릭·시스템 리소스 메트릭이 공유하는 저장 구조.

- 메모리: 스레드 안전 deque 링버퍼 (maxlen 고정 → 메모리 상한)
- 영속: jsonl append (Flask 재기동 시 최근 스냅샷 복구), 크기 초과 시 1회전
"""
import json
import logging
import os
import threading
from collections import deque

logger = logging.getLogger(__name__)


class MetricsHistory:

    def __init__(self, path: str, maxlen: int, max_bytes: int = 5 * 1024 * 1024):
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
