"""test_model_service.py — HF 검색·GGUF 파싱·Ollama 모델 관리 로직 검증"""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from service.model_service import ModelService


class FakeHttpResponse:
    """requests.get 응답 대역"""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f'HTTP {self.status_code}')


# ---------- HF 검색 ----------

def test_search_hf_models_parses_and_filters_gguf(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured['url'] = url
        captured['params'] = params
        return FakeHttpResponse(200, [
            {'id': 'unsloth/gemma-3-4b-it-GGUF', 'downloads': 1200, 'likes': 30,
             'lastModified': '2026-07-01T00:00:00.000Z'},
        ])

    monkeypatch.setattr('service.model_service.requests.get', fake_get)
    result = ModelService().search_hf_models('gemma')

    assert captured['params']['filter'] == 'gguf'
    assert captured['params']['sort'] == 'downloads'
    assert result == [{
        'repo_id': 'unsloth/gemma-3-4b-it-GGUF',
        'downloads': 1200,
        'likes': 30,
        'updated_at': '2026-07-01T00:00:00.000Z',
    }]


# ---------- GGUF 파일 목록 ----------

def test_list_hf_gguf_files_extracts_quant_and_ollama_name(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeHttpResponse(200, [
            {'path': 'gemma-3-4b-it-Q4_K_M.gguf', 'size': 2489000000, 'type': 'file'},
            {'path': 'gemma-3-4b-it-BF16.gguf', 'size': 8000000000, 'type': 'file'},
            {'path': 'README.md', 'size': 1000, 'type': 'file'},
        ])

    monkeypatch.setattr('service.model_service.requests.get', fake_get)
    files = ModelService().list_hf_gguf_files('unsloth/gemma-3-4b-it-GGUF')

    assert len(files) == 2
    assert files[0] == {
        'filename': 'gemma-3-4b-it-Q4_K_M.gguf',
        'size': 2489000000,
        'quant': 'Q4_K_M',
        'ollama_name': 'hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M',
    }
    assert files[1]['quant'] == 'BF16'


def test_list_hf_gguf_files_without_quant_tag(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeHttpResponse(200, [{'path': 'model.gguf', 'size': 100, 'type': 'file'}])

    monkeypatch.setattr('service.model_service.requests.get', fake_get)
    files = ModelService().list_hf_gguf_files('someone/repo')
    assert files[0]['quant'] is None
    assert files[0]['ollama_name'] == 'hf.co/someone/repo'


def test_list_hf_gguf_files_gated_repo_raises_permission_error(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeHttpResponse(403, {'error': 'gated'})

    monkeypatch.setattr('service.model_service.requests.get', fake_get)
    with pytest.raises(PermissionError):
        ModelService().list_hf_gguf_files('meta-llama/gated-repo')


# ---------- Ollama 설치 목록 / 삭제 / pull ----------

class FakeOllamaClient:
    """ollama.Client 대역 — list/show/delete/pull"""

    def __init__(self, models=None, capabilities=None, pull_events=None, pull_error=None):
        self._models = models or []
        self._capabilities = capabilities or {}
        self._pull_events = pull_events or []
        self._pull_error = pull_error
        self.deleted = []

    def list(self):
        return SimpleNamespace(models=self._models)

    def show(self, name):
        return SimpleNamespace(capabilities=self._capabilities.get(name, []))

    def delete(self, name):
        self.deleted.append(name)

    def pull(self, name, stream=True):
        if self._pull_error:
            raise self._pull_error
        return iter(self._pull_events)


def make_model(name, size=1000, family='gemma3', param='4.3B', quant='Q4_K_M'):
    return SimpleNamespace(
        model=name, size=size,
        modified_at=datetime(2026, 7, 16, 12, 0, 0),
        details=SimpleNamespace(parameter_size=param, quantization_level=quant, family=family),
    )


def test_list_installed_models_includes_vision_capability():
    svc = ModelService()
    svc.client = FakeOllamaClient(
        models=[make_model('gemma3:4b'), make_model('qwen3:0.6b')],
        capabilities={'gemma3:4b': ['completion', 'vision'], 'qwen3:0.6b': ['completion']},
    )
    models = svc.list_installed_models()
    assert [m['name'] for m in models] == ['gemma3:4b', 'qwen3:0.6b']
    assert models[0]['vision'] is True
    assert models[1]['vision'] is False
    assert models[0]['quantization'] == 'Q4_K_M'
    assert models[0]['modified_at'] == '2026-07-16T12:00:00'


def test_list_installed_models_show_failure_defaults_vision_false():
    class BrokenShowClient(FakeOllamaClient):
        def show(self, name):
            raise Exception('model not found')

    svc = ModelService()
    svc.client = BrokenShowClient(models=[make_model('gemma3:4b')])
    assert svc.list_installed_models()[0]['vision'] is False


def test_delete_model_calls_client():
    svc = ModelService()
    svc.client = FakeOllamaClient()
    svc.delete_model('gemma3:4b')
    assert svc.client.deleted == ['gemma3:4b']


def test_pull_model_stream_yields_ndjson_progress():
    svc = ModelService()
    svc.client = FakeOllamaClient(pull_events=[
        SimpleNamespace(status='pulling manifest', total=None, completed=None),
        SimpleNamespace(status='pulling abc123', total=100, completed=50),
        SimpleNamespace(status='success', total=None, completed=None),
    ])
    lines = [json.loads(line) for line in svc.pull_model_stream('hf.co/unsloth/x:Q4_K_M')]
    assert lines[0]['status'] == 'pulling manifest'
    assert lines[1] == {'status': 'pulling abc123', 'total': 100, 'completed': 50}
    assert lines[2]['status'] == 'success'


def test_pull_model_stream_yields_error_line_on_failure():
    svc = ModelService()
    svc.client = FakeOllamaClient(pull_error=Exception('pull model manifest: file does not exist'))
    lines = [json.loads(line) for line in svc.pull_model_stream('hf.co/bad/repo')]
    assert len(lines) == 1
    assert 'file does not exist' in lines[0]['error']
