"""
Download Queue Service
모델 다운로드를 메모리 큐에 쌓고 워커 스레드 1개가 순차 pull — 브라우저 연결과 무관하게 진행
"""
import logging
import threading
import uuid
from datetime import datetime

from ollama import Client

logger = logging.getLogger(__name__)


class DownloadQueueService:
    """다운로드 큐 관리 — enqueue/get_state (취소·이력 정리는 Task 2에서 추가)"""

    def __init__(self, ollama_url: str = 'http://127.0.0.1:11434'):
        # model_service와 동일하게 명시적 Client 생성 (OLLAMA_HOST 환경변수 비의존)
        self.client = Client(host=ollama_url.rstrip('/'))
        self._lock = threading.Lock()
        self._items = []                # 큐 + 완료 이력 (추가 순서 유지)
        self._wake = threading.Event()  # 워커 깨우기 — 빈 큐에서 busy-wait 방지
        self._worker = None

    def enqueue(self, name: str) -> dict:
        """큐에 추가. 같은 이름이 대기/진행 중이면 ValueError"""
        with self._lock:
            for item in self._items:
                if item['name'] == name and item['status'] in ('queued', 'pulling'):
                    raise ValueError(f'이미 큐에 있습니다: {name}')
            item = {
                'id': uuid.uuid4().hex,
                'name': name,
                'status': 'queued',
                'total': None,
                'completed': None,
                'error': None,
                'added_at': datetime.now().isoformat(timespec='seconds'),
                'finished_at': None,
            }
            self._items.append(item)
            self._ensure_worker()
        self._wake.set()
        return dict(item)

    def get_state(self) -> list:
        """전체 항목 스냅샷 (얕은 복사 — 폴링 응답용)"""
        with self._lock:
            return [dict(i) for i in self._items]

    # ---------- 워커 ----------

    def _ensure_worker(self):
        """(락 보유 상태) 워커 스레드 지연 기동 — 데몬이라 서버 종료를 막지 않음"""
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run, daemon=True, name='model-download-worker')
            self._worker.start()

    def _next_queued(self):
        """(락 획득) 다음 대기 항목을 pulling으로 전환해 반환, 없으면 None"""
        with self._lock:
            for item in self._items:
                if item['status'] == 'queued':
                    item['status'] = 'pulling'
                    return item
            return None

    def _run(self):
        while True:
            # clear를 조회보다 먼저 — 조회와 wait 사이에 들어온 enqueue를 놓치지 않기 위함
            self._wake.clear()
            item = self._next_queued()
            if item is None:
                self._wake.wait()
                continue
            self._pull(item)

    def _pull(self, item):
        """항목 1개 pull 실행 — 진행률 갱신, 실패해도 워커는 다음 항목 계속"""
        logger.info(f"Queue pull start: {item['name']}")
        try:
            for progress in self.client.pull(item['name'], stream=True):
                with self._lock:
                    item['total'] = progress.total
                    item['completed'] = progress.completed
            with self._lock:
                self._finish(item, 'done')
            logger.info(f"Queue pull done: {item['name']}")
        except Exception as e:
            with self._lock:
                item['error'] = str(e)
                self._finish(item, 'error')
            logger.error(f"Queue pull failed ({item['name']}): {str(e)}")

    def _finish(self, item, status: str):
        """(락 보유 상태) 종료 상태 기록"""
        item['status'] = status
        item['finished_at'] = datetime.now().isoformat(timespec='seconds')
