"""
Download Queue Service
모델 다운로드를 메모리 큐에 쌓고 워커 스레드 1개가 순차 pull — 브라우저 연결과 무관하게 진행
"""
import logging
import threading
import uuid
from datetime import datetime

from util.ollama_client import create_ollama_client

logger = logging.getLogger(__name__)

MAX_FINISHED_ITEMS = 20  # 완료/실패/취소 이력 보관 개수 — 폴링 응답 크기 제한


class DownloadQueueService:
    """다운로드 큐 관리 — enqueue/get_state/cancel, 완료 이력은 최근 20개만 유지"""

    def __init__(self, ollama_url: str = 'http://127.0.0.1:11434'):
        self.client = create_ollama_client(ollama_url)
        self._lock = threading.Lock()
        self._items = []                # 큐 + 완료 이력 (추가 순서 유지)
        self._wake = threading.Event()  # 워커 깨우기 — 빈 큐에서 busy-wait 방지
        self._worker = None
        self._cancel_ids = set()        # 취소 요청된 진행 중 항목 id

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

    def cancel(self, item_id: str) -> str:
        """대기 항목은 즉시 제거, 진행 중 항목은 취소 요청.

        진행 중 취소는 워커가 다음 진행률 청크에서 감지한다 (스트림이 멈춰 있으면 지연될 수 있음).
        대상이 없거나 이미 종료된 항목이면 KeyError.
        """
        with self._lock:
            for item in self._items:
                if item['id'] != item_id:
                    continue
                if item['status'] == 'queued':
                    self._items.remove(item)
                    return 'removed'
                if item['status'] == 'pulling':
                    self._cancel_ids.add(item_id)
                    return 'canceling'
                break  # 이미 종료된 항목 — 아래에서 KeyError
        raise KeyError(item_id)

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
        """항목 1개 pull 실행 — 진행률 갱신·취소 감지, 실패해도 워커는 다음 항목 계속"""
        logger.info(f"Queue pull start: {item['name']}")
        try:
            for progress in self.client.pull(item['name'], stream=True):
                with self._lock:
                    if item['id'] in self._cancel_ids:
                        self._finish(item, 'canceled')
                        logger.info(f"Queue pull canceled: {item['name']}")
                        # 루프 탈출로 제너레이터가 닫혀 HTTP 스트림도 중단된다.
                        # 받다 만 레이어는 Ollama가 캐시하므로 재시도 시 이어받는다.
                        return
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
        """(락 보유 상태) 종료 상태 기록 + 오래된 이력 정리"""
        item['status'] = status
        item['finished_at'] = datetime.now().isoformat(timespec='seconds')
        self._cancel_ids.discard(item['id'])
        finished = [i for i in self._items if i['status'] in ('done', 'error', 'canceled')]
        for old in finished[:-MAX_FINISHED_ITEMS]:
            self._items.remove(old)
