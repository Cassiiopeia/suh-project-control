"""test_ollama_client_factory.py — Ollama Client 공용 팩토리와 타임아웃 강제 검증 (#109)

Ollama 호출에 타임아웃이 없으면 waitress 워커 스레드가 무한 대기해
서버 전체가 행에 걸린다. 모든 서비스가 타임아웃 있는 공용 팩토리로
Client를 생성하는지 검증한다.
"""
import httpx
import pytest

import util.ollama_client as ollama_client_module
from util.ollama_client import create_ollama_client


class FakeClient:
    """ollama.Client 대역 — 생성 인자만 캡처"""

    def __init__(self, host=None, **kwargs):
        self.host = host
        self.kwargs = kwargs


# ---------- 팩토리 자체 ----------

def test_factory_sets_finite_timeout(monkeypatch):
    captured = {}

    def fake_client(host=None, **kwargs):
        captured['host'] = host
        captured.update(kwargs)
        return FakeClient(host=host, **kwargs)

    monkeypatch.setattr(ollama_client_module, 'Client', fake_client)
    create_ollama_client('http://127.0.0.1:11434/')

    # 후행 슬래시 정리
    assert captured['host'] == 'http://127.0.0.1:11434'
    # 타임아웃이 반드시 유한값으로 지정돼야 한다
    timeout = captured.get('timeout')
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read is not None and timeout.read > 0
    assert timeout.connect is not None and timeout.connect > 0


def test_factory_default_url(monkeypatch):
    captured = {}

    def fake_client(host=None, **kwargs):
        captured['host'] = host
        return FakeClient(host=host, **kwargs)

    monkeypatch.setattr(ollama_client_module, 'Client', fake_client)
    create_ollama_client()
    assert captured['host'] == 'http://127.0.0.1:11434'


# ---------- 모든 Ollama 사용 서비스가 팩토리를 쓰는지 ----------

SERVICE_CASES = [
    ('service.ollama_service', 'OllamaService'),
    ('service.ocr_service', 'OCRService'),
    ('service.vision_service', 'VisionService'),
    ('service.model_service', 'ModelService'),
    ('service.download_queue_service', 'DownloadQueueService'),
]


@pytest.mark.parametrize('module_path, class_name', SERVICE_CASES)
def test_services_use_factory(monkeypatch, module_path, class_name):
    import importlib
    module = importlib.import_module(module_path)

    called = {}

    def fake_factory(url='http://127.0.0.1:11434', timeout_sec=None):
        called['url'] = url
        return FakeClient(host=url)

    # 서비스 모듈 네임스페이스의 팩토리를 대체 — 팩토리 미사용이면 called가 비어 실패
    monkeypatch.setattr(module, 'create_ollama_client', fake_factory, raising=True)
    getattr(module, class_name)()
    assert 'url' in called
