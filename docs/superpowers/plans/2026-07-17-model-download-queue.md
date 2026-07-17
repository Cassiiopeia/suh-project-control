# 모델 다운로드 큐 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모델 다운로드를 서버 메모리 큐에 쌓아 워커 스레드가 순차 실행하고, 프론트는 폴링으로 진행률을 표시한다 (탭을 닫아도 다운로드 계속).

**Architecture:** 신규 `DownloadQueueService`가 메모리 큐 + 데몬 워커 스레드 1개를 관리한다. 라우터에 큐 API 3개(`POST/GET /models/queue`, `DELETE /models/queue/<id>`)를 추가하고 기존 스트리밍 `POST /models/pull`은 제거한다. 프론트는 '받기' 클릭 시 큐에 추가하고 1.5초 폴링으로 큐 패널을 그린다.

**Tech Stack:** Flask, ollama-python(Client.pull stream), threading, pytest(monkeypatch), 바닐라 JS + DaisyUI

**Spec:** `docs/superpowers/specs/2026-07-17-model-download-queue-design.md`

## Global Constraints

- 작업 디렉토리: `suh-ai-server/flask` (테스트는 이 디렉토리에서 `python -m pytest test/ -v`)
- Python >= 3.10, 외부 의존성 추가 금지 (threading 표준 라이브러리만 사용)
- 코드 주석은 한국어, WHY 중심으로 간결하게 (기존 파일 스타일 유지)
- 커밋 메시지는 한국어 `모델 다운로드 큐 : <타입> : <설명>` 형식, **Co-Authored-By 태그 금지**
- JS는 기존 `models.js` 스타일 유지: `function () {}` 표현식, `el()` 헬퍼, `apiFetch`/`showToast`/`escapeHtml` 전역 함수 사용 (base.html 제공)
- 큐 항목 상태값: `queued | pulling | done | error | canceled` (문자열 고정 — 프론트 배지 매핑과 일치해야 함)

---

### Task 1: DownloadQueueService — 큐 추가·순차 실행·완료/에러 전이

**Files:**
- Create: `suh-ai-server/flask/service/download_queue_service.py`
- Test: `suh-ai-server/flask/test/test_download_queue_service.py`

**Interfaces:**
- Consumes: `ollama.Client` (기존 `model_service.py`와 동일한 방식으로 생성)
- Produces (Task 2·3이 의존):
  - `DownloadQueueService(ollama_url: str = 'http://127.0.0.1:11434')`
  - `enqueue(name: str) -> dict` — 큐 항목 dict 반환, 중복 시 `ValueError`
  - `get_state() -> list[dict]` — 전체 항목 스냅샷 (추가 순서)
  - 항목 dict 키: `id, name, status, total, completed, error, added_at, finished_at`

- [ ] **Step 1: 실패하는 테스트 작성**

`suh-ai-server/flask/test/test_download_queue_service.py` 생성:

```python
"""test_download_queue_service.py — 다운로드 큐 서비스 검증 (ollama Client는 mock)"""
import threading
import time
from types import SimpleNamespace

import pytest

from service.download_queue_service import DownloadQueueService


def wait_until(cond, timeout=2.0):
    """워커 스레드의 상태 전이를 폴링으로 대기 — 타임아웃 시 False"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FakePullClient:
    """ollama.Client 대역 — pull 호출 순서 기록, 이름별 이벤트/에러 지정 가능"""

    def __init__(self, events=None, errors=None):
        self._events = events or {}   # name -> [SimpleNamespace(status,total,completed), ...]
        self._errors = errors or {}   # name -> Exception
        self.pulled = []              # pull이 호출된 이름 순서

    def pull(self, name, stream=True):
        self.pulled.append(name)
        if name in self._errors:
            raise self._errors[name]
        return iter(self._events.get(name, [
            SimpleNamespace(status='pulling abc', total=100, completed=50),
            SimpleNamespace(status='success', total=None, completed=None),
        ]))


def make_service(client):
    svc = DownloadQueueService()
    svc.client = client  # 워커는 첫 enqueue에서 기동하므로 그 전에 교체
    return svc


def find(svc, item_id):
    return next(i for i in svc.get_state() if i['id'] == item_id)


def test_enqueue_returns_queued_item_with_fields():
    svc = make_service(FakePullClient(events={'m1': []}))
    item = svc.enqueue('m1')
    assert item['name'] == 'm1'
    assert item['id']
    assert item['added_at']
    assert item['status'] in ('queued', 'pulling', 'done')  # 워커가 바로 집어갈 수 있음


def test_enqueue_duplicate_active_name_raises():
    # 진행 중 상태에서 중복을 확인해야 하므로 첫 청크에서 멈추는 제너레이터 사용
    gate = threading.Event()

    class SlowClient(FakePullClient):
        def pull(self, name, stream=True):
            self.pulled.append(name)
            def gen():
                yield SimpleNamespace(status='pulling', total=100, completed=10)
                gate.wait(timeout=2)
                yield SimpleNamespace(status='success', total=None, completed=None)
            return gen()

    svc = make_service(SlowClient())
    item = svc.enqueue('m1')
    assert wait_until(lambda: find(svc, item['id'])['status'] == 'pulling')
    with pytest.raises(ValueError):
        svc.enqueue('m1')
    gate.set()
    assert wait_until(lambda: find(svc, item['id'])['status'] == 'done')


def test_worker_processes_items_sequentially_to_done():
    client = FakePullClient(events={'m1': [], 'm2': []})
    svc = make_service(client)
    i1 = svc.enqueue('m1')
    i2 = svc.enqueue('m2')
    assert wait_until(lambda: find(svc, i2['id'])['status'] == 'done')
    assert find(svc, i1['id'])['status'] == 'done'
    assert client.pulled == ['m1', 'm2']  # 넣은 순서대로 순차 실행
    assert find(svc, i1['id'])['finished_at']


def test_pull_progress_updates_total_and_completed():
    gate = threading.Event()

    class ProgressClient(FakePullClient):
        def pull(self, name, stream=True):
            def gen():
                yield SimpleNamespace(status='pulling layer', total=200, completed=80)
                gate.wait(timeout=2)
                yield SimpleNamespace(status='success', total=None, completed=None)
            return gen()

    svc = make_service(ProgressClient())
    item = svc.enqueue('m1')
    assert wait_until(lambda: find(svc, item['id'])['completed'] == 80)
    assert find(svc, item['id'])['total'] == 200
    gate.set()
    assert wait_until(lambda: find(svc, item['id'])['status'] == 'done')


def test_pull_error_marks_item_and_continues_to_next():
    client = FakePullClient(
        events={'good': []},
        errors={'bad': Exception('pull model manifest: file does not exist')},
    )
    svc = make_service(client)
    bad = svc.enqueue('bad')
    good = svc.enqueue('good')
    assert wait_until(lambda: find(svc, good['id'])['status'] == 'done')
    bad_item = find(svc, bad['id'])
    assert bad_item['status'] == 'error'
    assert 'file does not exist' in bad_item['error']
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_download_queue_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'service.download_queue_service'`

- [ ] **Step 3: 최소 구현 작성**

`suh-ai-server/flask/service/download_queue_service.py` 생성:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_download_queue_service.py -v`
Expected: PASS (5개)

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/download_queue_service.py suh-ai-server/flask/test/test_download_queue_service.py
git commit -m "모델 다운로드 큐 : feat : 메모리 큐 서비스·워커 스레드 순차 실행 구현"
```

---

### Task 2: DownloadQueueService — 취소·대기 제거·이력 정리

**Files:**
- Modify: `suh-ai-server/flask/service/download_queue_service.py`
- Test: `suh-ai-server/flask/test/test_download_queue_service.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `DownloadQueueService`
- Produces (Task 3이 의존):
  - `cancel(item_id: str) -> str` — 대기 항목이면 목록에서 제거 후 `'removed'`, 진행 중이면 취소 요청 후 `'canceling'` 반환. 대상이 없거나 이미 종료된 항목이면 `KeyError`
  - 종료 항목(done/error/canceled)은 최근 20개까지만 유지 (`MAX_FINISHED_ITEMS`)

- [ ] **Step 1: 실패하는 테스트 작성**

`test_download_queue_service.py` 끝에 추가:

```python
def test_cancel_queued_item_removes_it():
    # 첫 항목이 게이트에 막혀 있는 동안 두 번째(대기) 항목을 제거
    gate = threading.Event()

    class SlowClient(FakePullClient):
        def pull(self, name, stream=True):
            self.pulled.append(name)
            def gen():
                yield SimpleNamespace(status='pulling', total=100, completed=10)
                gate.wait(timeout=2)
                yield SimpleNamespace(status='success', total=None, completed=None)
            return gen()

    svc = make_service(SlowClient())
    first = svc.enqueue('m1')
    second = svc.enqueue('m2')
    assert wait_until(lambda: find(svc, first['id'])['status'] == 'pulling')
    assert svc.cancel(second['id']) == 'removed'
    assert all(i['id'] != second['id'] for i in svc.get_state())
    gate.set()
    assert wait_until(lambda: find(svc, first['id'])['status'] == 'done')


def test_cancel_pulling_item_stops_and_worker_continues():
    gate = threading.Event()

    class SlowClient(FakePullClient):
        def pull(self, name, stream=True):
            self.pulled.append(name)
            if name == 'slow':
                def gen():
                    yield SimpleNamespace(status='pulling', total=100, completed=10)
                    gate.wait(timeout=2)
                    yield SimpleNamespace(status='pulling', total=100, completed=90)
                    yield SimpleNamespace(status='success', total=None, completed=None)
                return gen()
            return iter([SimpleNamespace(status='success', total=None, completed=None)])

    client = SlowClient()
    svc = make_service(client)
    slow = svc.enqueue('slow')
    nxt = svc.enqueue('next')
    assert wait_until(lambda: find(svc, slow['id'])['status'] == 'pulling')
    assert svc.cancel(slow['id']) == 'canceling'
    gate.set()  # 다음 청크에서 취소 플래그가 감지된다
    assert wait_until(lambda: find(svc, slow['id'])['status'] == 'canceled')
    assert wait_until(lambda: find(svc, nxt['id'])['status'] == 'done')
    assert client.pulled == ['slow', 'next']


def test_cancel_unknown_or_finished_item_raises_keyerror():
    svc = make_service(FakePullClient(events={'m1': []}))
    item = svc.enqueue('m1')
    assert wait_until(lambda: find(svc, item['id'])['status'] == 'done')
    with pytest.raises(KeyError):
        svc.cancel(item['id'])  # 이미 종료된 항목
    with pytest.raises(KeyError):
        svc.cancel('no-such-id')


def test_finished_items_trimmed_to_max_20():
    names = [f'm{n}' for n in range(25)]
    client = FakePullClient(events={name: [] for name in names})
    svc = make_service(client)
    last = None
    for name in names:
        last = svc.enqueue(name)
    assert wait_until(lambda: find(svc, last['id'])['status'] == 'done', timeout=5.0)
    finished = [i for i in svc.get_state()
                if i['status'] in ('done', 'error', 'canceled')]
    assert len(finished) == 20
    # 오래된 것부터 정리 — 마지막에 넣은 항목은 남아 있어야 한다
    assert any(i['id'] == last['id'] for i in finished)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_download_queue_service.py -v`
Expected: 신규 4개 FAIL — `AttributeError: 'DownloadQueueService' object has no attribute 'cancel'` 및 트림 미구현으로 `len(finished) == 20` 실패

- [ ] **Step 3: 구현**

`download_queue_service.py` 수정. 먼저 모듈 상수와 `__init__`에 취소 플래그 추가:

```python
logger = logging.getLogger(__name__)

MAX_FINISHED_ITEMS = 20  # 완료/실패/취소 이력 보관 개수 — 폴링 응답 크기 제한
```

`__init__`의 `self._worker = None` 아래에 추가:

```python
        self._cancel_ids = set()        # 취소 요청된 진행 중 항목 id
```

`get_state` 아래에 `cancel` 메서드 추가:

```python
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
```

`_pull`의 진행률 루프를 취소 감지 버전으로 교체 (기존 `for progress ...` 블록 전체):

```python
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
```

`_finish`를 이력 정리 포함 버전으로 교체:

```python
    def _finish(self, item, status: str):
        """(락 보유 상태) 종료 상태 기록 + 오래된 이력 정리"""
        item['status'] = status
        item['finished_at'] = datetime.now().isoformat(timespec='seconds')
        self._cancel_ids.discard(item['id'])
        finished = [i for i in self._items if i['status'] in ('done', 'error', 'canceled')]
        for old in finished[:-MAX_FINISHED_ITEMS]:
            self._items.remove(old)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_download_queue_service.py -v`
Expected: PASS (9개)

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/download_queue_service.py suh-ai-server/flask/test/test_download_queue_service.py
git commit -m "모델 다운로드 큐 : feat : 취소·대기 제거·완료 이력 20개 정리 추가"
```

---

### Task 3: 큐 API 라우터 + 기존 /models/pull 제거

**Files:**
- Modify: `suh-ai-server/flask/router/model_router.py`
- Modify: `suh-ai-server/flask/service/model_service.py` (`pull_model_stream` 제거)
- Test: `suh-ai-server/flask/test/test_model_router.py`, `suh-ai-server/flask/test/test_model_service.py`

**Interfaces:**
- Consumes: Task 2의 `DownloadQueueService.enqueue/get_state/cancel`
- Produces (Task 4 프론트가 의존):
  - `POST /models/queue` body `{name}` → 200 `{'success': True, 'queue': [...]}`, 중복 409, name 없음 400
  - `GET /models/queue` → 200 `{'success': True, 'queue': [...]}`
  - `DELETE /models/queue/<item_id>` → 200 `{'success': True, 'result': 'removed'|'canceling'}`, 없는 id 404
  - `router/model_router.py` 모듈 전역 `queue_service` (테스트에서 monkeypatch 대상)

- [ ] **Step 1: 실패하는 테스트 작성**

`test_model_router.py`에서 기존 `test_pull_requires_name`, `test_pull_streams_ndjson_with_no_buffering_header` 두 함수와 상단 `import json`을 삭제하고, 파일 끝에 추가:

```python
# ---------- 다운로드 큐 ----------

def test_queue_add_requires_name(client):
    assert client.post('/models/queue', json={}).status_code == 400


def test_queue_add_returns_queue_state(client, monkeypatch):
    added = []
    monkeypatch.setattr(model_router_module.queue_service, 'enqueue',
                        lambda name: added.append(name))
    monkeypatch.setattr(model_router_module.queue_service, 'get_state',
                        lambda: [{'id': 'a1', 'name': 'hf.co/unsloth/x:Q4_K_M', 'status': 'queued'}])
    resp = client.post('/models/queue', json={'name': 'hf.co/unsloth/x:Q4_K_M'})
    assert resp.status_code == 200
    assert added == ['hf.co/unsloth/x:Q4_K_M']
    assert resp.get_json()['queue'][0]['status'] == 'queued'


def test_queue_add_duplicate_returns_409(client, monkeypatch):
    def dup(name):
        raise ValueError(f'이미 큐에 있습니다: {name}')

    monkeypatch.setattr(model_router_module.queue_service, 'enqueue', dup)
    resp = client.post('/models/queue', json={'name': 'x'})
    assert resp.status_code == 409
    assert '이미 큐에' in resp.get_json()['error']


def test_queue_state_returns_items(client, monkeypatch):
    monkeypatch.setattr(model_router_module.queue_service, 'get_state',
                        lambda: [{'id': 'a1', 'status': 'pulling', 'total': 100, 'completed': 50}])
    resp = client.get('/models/queue')
    assert resp.status_code == 200
    assert resp.get_json()['queue'][0]['completed'] == 50


def test_queue_cancel_returns_result(client, monkeypatch):
    canceled = []

    def fake_cancel(item_id):
        canceled.append(item_id)
        return 'canceling'

    monkeypatch.setattr(model_router_module.queue_service, 'cancel', fake_cancel)
    resp = client.delete('/models/queue/a1')
    assert resp.status_code == 200
    assert resp.get_json()['result'] == 'canceling'
    assert canceled == ['a1']


def test_queue_cancel_unknown_id_returns_404(client, monkeypatch):
    def missing(item_id):
        raise KeyError(item_id)

    monkeypatch.setattr(model_router_module.queue_service, 'cancel', missing)
    assert client.delete('/models/queue/nope').status_code == 404
```

`test_model_service.py`에서 pull 관련 삭제:
- `test_pull_model_stream_yields_ndjson_progress`, `test_pull_model_stream_yields_error_line_on_failure` 두 함수 삭제
- `FakeOllamaClient`의 `pull_events`/`pull_error` 파라미터와 `pull` 메서드 삭제 (list/show/delete만 남김)
- 상단 `import json` 삭제
- 섹션 주석을 `# ---------- Ollama 설치 목록 / 삭제 ----------`로 변경

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_model_router.py test/test_model_service.py -v`
Expected: 신규 큐 테스트 6개 FAIL — `AttributeError: module 'router.model_router' has no attribute 'queue_service'`. 나머지는 PASS

- [ ] **Step 3: 구현**

`router/model_router.py` 수정:

상단 import와 전역에 큐 서비스 추가:

```python
from flask import Blueprint, jsonify, request
from service.download_queue_service import DownloadQueueService
from service.model_service import ModelService
import logging

logger = logging.getLogger(__name__)

model_bp = Blueprint('model', __name__)
model_service = ModelService()
queue_service = DownloadQueueService()
```

(`Response` import는 pull 제거로 더 이상 불필요 — 제거)

기존 `pull_model` 함수(`@model_bp.route('/models/pull', ...)` 블록 전체)를 삭제하고 아래로 교체:

```python
@model_bp.route('/models/queue', methods=['POST'])
def enqueue_download():
    """모델 다운로드 큐 추가 — 워커가 순차 실행하므로 브라우저를 닫아도 진행된다"""
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip() if isinstance(data.get('name'), str) else ''
    if not name:
        return jsonify({'error': 'name is required'}), 400
    try:
        queue_service.enqueue(name)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409
    logger.info(f"Model queued: {name}")
    return jsonify({'success': True, 'queue': queue_service.get_state()}), 200


@model_bp.route('/models/queue', methods=['GET'])
def queue_state():
    """다운로드 큐 상태 조회 (프론트 폴링용)"""
    return jsonify({'success': True, 'queue': queue_service.get_state()}), 200


@model_bp.route('/models/queue/<item_id>', methods=['DELETE'])
def cancel_download(item_id):
    """대기 항목 제거 또는 진행 중 다운로드 취소"""
    try:
        result = queue_service.cancel(item_id)
    except KeyError:
        return jsonify({'error': '해당 항목을 찾을 수 없습니다'}), 404
    logger.info(f"Model queue cancel: {item_id} -> {result}")
    return jsonify({'success': True, 'result': result}), 200
```

`service/model_service.py`에서 `pull_model_stream` 메서드 전체(111~129행)와 상단 `import json` 삭제. 파일 docstring을 `HF 허브 검색·GGUF 파일 조회 + Ollama 삭제/설치 목록(vision capability 포함)`으로 갱신.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/ -v`
Expected: 전체 PASS (pull 관련 테스트는 삭제됨, 큐 테스트 6개 포함)

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/router/model_router.py suh-ai-server/flask/service/model_service.py suh-ai-server/flask/test/test_model_router.py suh-ai-server/flask/test/test_model_service.py
git commit -m "모델 다운로드 큐 : feat : 큐 API 추가 및 스트리밍 pull 엔드포인트 제거"
```

---

### Task 4: 프론트엔드 — 큐 패널·폴링

**Files:**
- Modify: `suh-ai-server/flask/templates/admin/models.html:70-81` (pull-wrap 교체)
- Modify: `suh-ai-server/flask/static/js/models.js` (pull 로직 교체)

**Interfaces:**
- Consumes: Task 3의 큐 API 3개. base.html 전역 `apiFetch`/`showToast`/`escapeHtml`
- Produces: 사용자 화면의 큐 패널 (자동 폴링·상태 배지·진행률·취소 버튼)

- [ ] **Step 1: models.html의 pull-wrap을 큐 패널로 교체**

71~81행의 `<!-- 다운로드 진행률 --> ... </div>` 블록(`pull-wrap` div 전체)을 아래로 교체:

```html
      <!-- 다운로드 큐 — 서버 워커가 순차 실행, 탭을 닫아도 계속 진행 -->
      <div id="queue-wrap" class="hidden border border-base-300 rounded-lg p-3 space-y-2">
        <h3 class="font-semibold text-sm flex items-center gap-2">
          <i data-lucide="download" class="size-4 text-primary"></i>다운로드 큐
        </h3>
        <div id="queue-body" class="space-y-2"></div>
      </div>
```

- [ ] **Step 2: models.js의 pull 로직을 큐 로직으로 교체**

상단 전역 변수(4~8행)에서 `pullController`, `pullErrorMessage`를 삭제하고 큐 폴링 변수로 교체:

```js
let installedModels = [];   // GET /models/installed 결과 캐시
let queuePollTimer = null;  // 큐 폴링 타이머 — 대기/진행 항목이 있을 때만 동작
let queueSnapshot = [];     // 직전 폴링 결과 (완료 전이 감지용)
let benchRunning = false;
let deleteTarget = null;
```

`/* ---------- 다운로드 (pull) ---------- */` 섹션 전체(`startPull`, `handlePullLine`, `cancelPull` 함수)를 아래로 교체:

```js
/* ---------- 다운로드 큐 ---------- */
async function enqueuePull(name) {
  try {
    const resp = await apiFetch(MODELS_API + '/queue', {
      method: 'POST',
      body: JSON.stringify({ name: name }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
    showToast(name + ' 큐에 추가했습니다', 'success');
    queueSnapshot = data.queue;
    renderQueue(data.queue);
    startQueuePolling();
  } catch (e) {
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('큐 추가 실패: ' + e.message, 'error');
    }
  }
}

function startQueuePolling() {
  if (queuePollTimer) return;
  queuePollTimer = setInterval(pollQueue, 1500);
}

function stopQueuePolling() {
  if (queuePollTimer) { clearInterval(queuePollTimer); queuePollTimer = null; }
}

async function pollQueue() {
  try {
    const resp = await apiFetch(MODELS_API + '/queue');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '큐 조회 실패');
    notifyFinished(queueSnapshot, data.queue);
    queueSnapshot = data.queue;
    renderQueue(data.queue);
    const active = data.queue.some(function (i) {
      return i.status === 'queued' || i.status === 'pulling';
    });
    if (active) startQueuePolling(); else stopQueuePolling();
  } catch (e) {
    stopQueuePolling(); // 인증 만료 등 — 다음 사용자 조작에서 재개
  }
}

/* 직전 폴링과 비교해 이번에 끝난 항목을 토스트로 알리고 설치 목록을 갱신 */
function notifyFinished(prev, next) {
  const wasActive = {};
  prev.forEach(function (i) {
    if (i.status === 'queued' || i.status === 'pulling') wasActive[i.id] = true;
  });
  let anyDone = false;
  next.forEach(function (i) {
    if (!wasActive[i.id]) return;
    if (i.status === 'done') {
      showToast(i.name + ' 다운로드 완료', 'success');
      anyDone = true;
    } else if (i.status === 'error') {
      showToast(i.name + ' 다운로드 실패: ' + (i.error || '')
        + ' — 이 레포는 Ollama 직접 가져오기를 지원하지 않는 구조일 수 있습니다', 'error');
    } else if (i.status === 'canceled') {
      showToast(i.name + ' 다운로드를 취소했습니다. 다시 받으면 이어서 받습니다.', 'info');
    }
  });
  if (anyDone) loadInstalled();
}

const QUEUE_BADGE = {
  queued: ['badge-ghost', '대기'],
  pulling: ['badge-info', '다운로드 중'],
  done: ['badge-success', '완료'],
  error: ['badge-error', '실패'],
  canceled: ['badge-warning', '취소'],
};

function renderQueue(items) {
  const wrap = el('queue-wrap');
  const body = el('queue-body');
  if (!items.length) { wrap.classList.add('hidden'); return; }
  wrap.classList.remove('hidden');
  body.innerHTML = items.map(function (i) {
    const badge = QUEUE_BADGE[i.status] || ['badge-ghost', i.status];
    let html = '<div class="border border-base-300 rounded-lg p-2 space-y-1">'
      + '<div class="flex items-center justify-between gap-2">'
      + '<span class="text-sm font-mono break-all">' + escapeHtml(i.name) + '</span>'
      + '<span class="flex items-center gap-2 shrink-0">'
      + '<span class="badge badge-sm ' + badge[0] + '">' + badge[1] + '</span>';
    if (i.status === 'queued' || i.status === 'pulling') {
      html += '<button class="btn btn-error btn-xs" data-qcancel="' + escapeHtml(i.id) + '">'
        + (i.status === 'queued' ? '제거' : '취소') + '</button>';
    }
    html += '</span></div>';
    if (i.status === 'pulling') {
      const percent = (i.total && i.completed) ? Math.round((i.completed / i.total) * 100) : 0;
      html += '<progress class="progress progress-primary w-full" value="' + percent + '" max="100"></progress>'
        + '<div class="text-xs opacity-70 text-right">'
        + fmtSize(i.completed || 0) + ' / ' + fmtSize(i.total || 0) + ' (' + percent + '%)</div>';
    } else if (i.status === 'error' && i.error) {
      html += '<div class="text-xs text-error">' + escapeHtml(i.error) + '</div>';
    }
    return html + '</div>';
  }).join('');
  body.querySelectorAll('[data-qcancel]').forEach(function (btn) {
    btn.addEventListener('click', function () { cancelQueueItem(btn.dataset.qcancel); });
  });
}

async function cancelQueueItem(itemId) {
  try {
    const resp = await apiFetch(MODELS_API + '/queue/' + encodeURIComponent(itemId), { method: 'DELETE' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '취소 실패');
    pollQueue(); // 즉시 갱신 — 다음 폴링 주기를 기다리지 않음
  } catch (e) {
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('취소 실패: ' + e.message, 'error');
    }
  }
}
```

`loadFiles` 안의 받기 버튼 핸들러에서 `startPull` → `enqueuePull`로 변경:

```js
    body.querySelectorAll('[data-pull]').forEach(function (btn) {
      btn.addEventListener('click', function () { enqueuePull(btn.dataset.pull); });
    });
```

`DOMContentLoaded` 초기화에서 `el('pull-cancel').addEventListener('click', cancelPull);` 줄을 삭제하고, `loadInstalled();` 아래에 페이지 로드 시 큐 상태 복원을 추가:

```js
document.addEventListener('DOMContentLoaded', function () {
  loadInstalled();
  pollQueue(); // 새로고침해도 진행 중인 큐 상태 복원 — 활성 항목 있으면 폴링 자동 시작
  el('installed-refresh').addEventListener('click', loadInstalled);
  el('search-btn').addEventListener('click', searchHf);
  el('search-input').addEventListener('keydown', function (e) { if (e.key === 'Enter') searchHf(); });
  el('delete-confirm').addEventListener('click', doDelete);
  el('bench-run').addEventListener('click', runBenchmark);
  el('bench-file').addEventListener('change', renderBenchModels);
  el('bench-url').addEventListener('input', renderBenchModels);
});
```

- [ ] **Step 3: 정적 검증**

Run: `node --check suh-ai-server/flask/static/js/models.js && grep -c "pullController\|startPull\|handlePullLine\|cancelPull\|pull-wrap" suh-ai-server/flask/static/js/models.js suh-ai-server/flask/templates/admin/models.html || true`
Expected: 문법 오류 없음, 두 파일 모두 매치 0건

- [ ] **Step 4: 전체 테스트 재확인**

Run: `cd suh-ai-server/flask && python -m pytest test/ -v`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/templates/admin/models.html suh-ai-server/flask/static/js/models.js
git commit -m "모델 다운로드 큐 : feat : 큐 패널 UI·1.5초 폴링·항목별 취소 구현"
```

---

### Task 5: 통합 검증 (수동)

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 테스트**

Run: `cd suh-ai-server/flask && python -m pytest test/ -v`
Expected: 전체 PASS

- [ ] **Step 2: 로컬 서버 수동 확인 (Ollama가 실행 중일 때)**

1. Flask 서버 기동 후 `/admin/models` 접속
2. HF 검색에서 작은 모델(예: `hf.co/Mungert/HyperCLOVAX-SEED-Text-Instruct-0.5B-GGUF:IQ3_M`) '받기' 연속 2~3개 클릭 → 큐 패널에 대기/다운로드 중 항목이 쌓이는지 확인
3. 새로고침 → 큐 상태가 복원되고 폴링이 재개되는지 확인
4. 진행 중 항목 '취소' → 취소 배지 전환 후 다음 항목이 자동 시작되는지 확인
5. 전부 완료 후 설치 목록에 모델이 나타나고 폴링이 멈추는지 확인 (개발자 도구 네트워크 탭)

체크 결과 이상 없으면 완료. 문제 발견 시 해당 Task로 돌아가 수정 후 재검증.
