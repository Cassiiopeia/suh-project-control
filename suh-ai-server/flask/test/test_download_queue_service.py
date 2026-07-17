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
