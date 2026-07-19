"""test_model_service.py — HF 검색·GGUF 파싱·Ollama 모델 관리 로직 검증"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from service.model_service import ModelService


class FakeHttpResponse:
    """requests.get 응답 대역"""

    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.text = text

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


# ---------- Ollama 라이브러리 검색 (ollama.com 파싱) ----------

# ollama.com/search 실제 마크업 축약본 — 클래스 패턴이 파싱 기준
OLLAMA_SEARCH_HTML = '''
<ul role="list" class="grid grid-cols-1">
<li  class="flex items-baseline border-b border-neutral-200 py-6">
  <a href="/library/gemma3" class="group w-full">
    <h2><span >gemma3</span></h2>
    <p class="max-w-lg break-words text-neutral-800 text-md">The current, most capable model
      that runs on a single GPU.</p>
    <span  class="inline-flex text-xs font-medium text-indigo-600 sm:text-[13px]">vision</span>
    <span  class="inline-flex text-xs font-medium text-blue-600 sm:text-[13px]">1b</span>
    <span  class="inline-flex text-xs font-medium text-blue-600 sm:text-[13px]">4b</span>
    <span class="flex items-center"><span >38.7M</span><span class="hidden sm:flex">&nbsp;Pulls</span></span>
  </a>
</li>
<li  class="flex items-baseline border-b border-neutral-200 py-6">
  <a href="/library/embeddinggemma" class="group w-full">
    <h2><span >embeddinggemma</span></h2>
    <p class="max-w-lg break-words text-neutral-800 text-md">Embedding model.</p>
    <span class="flex items-center"><span >1.2M</span><span class="hidden sm:flex">&nbsp;Pulls</span></span>
  </a>
</li>
</ul>
'''

# ollama.com/library/{name}/tags 축약본 — 모바일/데스크톱 중복 앵커 포함
OLLAMA_TAGS_HTML = '''
<a href="/library/gemma3:latest" class="md:hidden flex flex-col">
  <span class="font-mono">a2af6cc3eb7f</span> • 3.3GB • 128K context window
</a>
<a href="/library/gemma3:latest" class="group-hover:underline">gemma3:latest</a>
<a href="/library/gemma3:1b" class="md:hidden flex flex-col">
  <span class="font-mono">8648f39daa8f</span> • 815MB • 32K context window
</a>
<a href="/library/gemma3:1b" class="group-hover:underline">gemma3:1b</a>
'''


def test_search_ollama_models_parses_items(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured['url'] = url
        captured['params'] = params
        return FakeHttpResponse(200, text=OLLAMA_SEARCH_HTML)

    monkeypatch.setattr('service.model_service.requests.get', fake_get)
    results = ModelService().search_ollama_models('gemma')

    assert captured['url'].endswith('/search')
    assert captured['params'] == {'q': 'gemma'}
    assert len(results) == 2
    assert results[0]['name'] == 'gemma3'
    assert results[0]['pulls'] == '38.7M'
    assert results[0]['capabilities'] == ['vision']
    assert results[0]['sizes'] == ['1b', '4b']
    assert 'single GPU' in results[0]['description']
    assert results[1] == {'name': 'embeddinggemma', 'description': 'Embedding model.',
                          'pulls': '1.2M', 'capabilities': [], 'sizes': []}


def test_search_ollama_models_broken_html_returns_empty(monkeypatch):
    monkeypatch.setattr('service.model_service.requests.get',
                        lambda *a, **k: FakeHttpResponse(200, text='<html>redesigned</html>'))
    assert ModelService().search_ollama_models('gemma') == []


def test_list_ollama_tags_dedups_and_parses_info(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert url.endswith('/library/gemma3/tags')
        return FakeHttpResponse(200, text=OLLAMA_TAGS_HTML)

    monkeypatch.setattr('service.model_service.requests.get', fake_get)
    tags = ModelService().list_ollama_tags('gemma3')

    assert [t['tag'] for t in tags] == ['latest', '1b']
    assert tags[0] == {'tag': 'latest', 'full_name': 'gemma3:latest',
                       'digest': 'a2af6cc3eb7f', 'size_text': '3.3GB', 'context': '128K'}
    assert tags[1]['size_text'] == '815MB'


def test_list_ollama_tags_http_error_raises(monkeypatch):
    monkeypatch.setattr('service.model_service.requests.get',
                        lambda *a, **k: FakeHttpResponse(500))
    with pytest.raises(Exception):
        ModelService().list_ollama_tags('gemma3')


# ---------- Ollama 설치 목록 / 삭제 ----------

class FakeOllamaClient:
    """ollama.Client 대역 — list/show/delete"""

    def __init__(self, models=None, capabilities=None):
        self._models = models or []
        self._capabilities = capabilities or {}
        self.deleted = []

    def list(self):
        return SimpleNamespace(models=self._models)

    def show(self, name):
        return SimpleNamespace(capabilities=self._capabilities.get(name, []))

    def delete(self, name):
        self.deleted.append(name)


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
