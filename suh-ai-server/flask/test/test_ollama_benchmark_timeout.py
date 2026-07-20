"""벤치마크 전용 타임아웃 분리 테스트

reasoning 모델(exaone-deep 등)은 정상 동작 중에도 300초를 넘기므로 벤치마크
경로만 상한을 길게 쓴다. 일반 서비스는 300초를 유지해야 #109(Flask 워커
무한 대기로 전체 요청 중단)가 재발하지 않는다.
"""
import httpx

from service.ollama_service import OllamaService
from util.ollama_client import (
    OLLAMA_TIMEOUT_SEC,
    OLLAMA_BENCHMARK_TIMEOUT_SEC,
    create_ollama_client,
)


def test_benchmark_timeout_is_longer_than_default():
    assert OLLAMA_BENCHMARK_TIMEOUT_SEC > OLLAMA_TIMEOUT_SEC


def test_default_client_keeps_300s():
    """일반 서비스 상한은 그대로 300초여야 한다 (#109 안전장치)"""
    client = create_ollama_client()
    assert client._client.timeout.read == OLLAMA_TIMEOUT_SEC


def test_explicit_timeout_is_applied():
    client = create_ollama_client(timeout_sec=1800)
    assert client._client.timeout.read == 1800


def test_connect_timeout_stays_short():
    """Ollama 다운 시 빠르게 실패해야 하므로 connect는 길어지면 안 된다"""
    client = create_ollama_client(timeout_sec=1800)
    assert client._client.timeout.connect == 5


def test_service_builds_separate_clients():
    svc = OllamaService()
    assert svc.client._client.timeout.read == OLLAMA_TIMEOUT_SEC
    assert svc.benchmark_client._client.timeout.read == OLLAMA_BENCHMARK_TIMEOUT_SEC


def test_benchmark_call_uses_benchmark_client(monkeypatch):
    """auto_unload=True면 긴 상한의 benchmark_client가 쓰여야 한다"""
    svc = OllamaService()
    used = {}

    class _Msg:
        content = '{}'

    class _Resp:
        message = _Msg()
        total_duration = eval_duration = 1_000_000
        load_duration = 0
        prompt_eval_count = eval_count = 1

    def make(tag):
        def chat(**kwargs):
            used['tag'] = tag
            return _Resp()
        return chat

    monkeypatch.setattr(svc.benchmark_client, 'chat', make('benchmark'))
    monkeypatch.setattr(svc.client, 'chat', make('default'))
    monkeypatch.setattr(svc, 'unload_vram_model', lambda model_name=None: True)

    svc.chat(model='exaone-deep:7.8b', prompt='hi', auto_unload=True)
    assert used['tag'] == 'benchmark'

    svc.chat(model='gemma3:4b', prompt='hi', auto_unload=False)
    assert used['tag'] == 'default'
