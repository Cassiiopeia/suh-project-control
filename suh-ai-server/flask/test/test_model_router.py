"""test_model_router.py — /models/* 엔드포인트 동작 검증 (서비스는 mock)"""
import pytest
from flask import Flask

import router.model_router as model_router_module
from router.model_router import model_bp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(model_bp)
    return app.test_client()


def test_installed_returns_models(client, monkeypatch):
    monkeypatch.setattr(model_router_module.model_service, 'list_installed_models',
                        lambda: [{'name': 'gemma3:4b', 'vision': True}])
    resp = client.get('/models/installed')
    assert resp.status_code == 200
    assert resp.get_json() == {'success': True, 'models': [{'name': 'gemma3:4b', 'vision': True}]}


def test_installed_ollama_down_returns_500(client, monkeypatch):
    def boom():
        raise Exception('connection refused')

    monkeypatch.setattr(model_router_module.model_service, 'list_installed_models', boom)
    resp = client.get('/models/installed')
    assert resp.status_code == 500
    assert 'error' in resp.get_json()


def test_delete_requires_name(client):
    assert client.delete('/models/installed').status_code == 400


def test_delete_calls_service(client, monkeypatch):
    deleted = []
    monkeypatch.setattr(model_router_module.model_service, 'delete_model', deleted.append)
    resp = client.delete('/models/installed?name=hf.co/unsloth/x:Q4_K_M')
    assert resp.status_code == 200
    assert deleted == ['hf.co/unsloth/x:Q4_K_M']


def test_search_requires_query(client):
    assert client.get('/models/search').status_code == 400


def test_search_returns_results(client, monkeypatch):
    monkeypatch.setattr(model_router_module.model_service, 'search_hf_models',
                        lambda q: [{'repo_id': 'unsloth/gemma-GGUF'}])
    resp = client.get('/models/search?q=gemma')
    assert resp.status_code == 200
    assert resp.get_json()['results'][0]['repo_id'] == 'unsloth/gemma-GGUF'


def test_ollama_search_requires_query(client):
    assert client.get('/models/ollama/search').status_code == 400


def test_ollama_search_returns_results(client, monkeypatch):
    monkeypatch.setattr(model_router_module.model_service, 'search_ollama_models',
                        lambda q: [{'name': 'gemma3', 'pulls': '38.7M'}])
    resp = client.get('/models/ollama/search?q=gemma')
    assert resp.status_code == 200
    assert resp.get_json()['results'][0]['name'] == 'gemma3'


def test_ollama_search_failure_returns_500(client, monkeypatch):
    def boom(q):
        raise Exception('site changed')

    monkeypatch.setattr(model_router_module.model_service, 'search_ollama_models', boom)
    resp = client.get('/models/ollama/search?q=gemma')
    assert resp.status_code == 500
    assert 'error' in resp.get_json()


def test_ollama_tags_requires_name(client):
    assert client.get('/models/ollama/tags').status_code == 400


def test_ollama_tags_returns_tags(client, monkeypatch):
    monkeypatch.setattr(model_router_module.model_service, 'list_ollama_tags',
                        lambda name: [{'tag': '4b', 'full_name': 'gemma3:4b', 'size_text': '3.3GB'}])
    resp = client.get('/models/ollama/tags?name=gemma3')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['name'] == 'gemma3'
    assert body['tags'][0]['full_name'] == 'gemma3:4b'


def test_ollama_tags_failure_returns_500(client, monkeypatch):
    def boom(name):
        raise Exception('connection refused')

    monkeypatch.setattr(model_router_module.model_service, 'list_ollama_tags', boom)
    assert client.get('/models/ollama/tags?name=gemma3').status_code == 500


def test_hf_files_requires_repo(client):
    assert client.get('/models/hf/files').status_code == 400


def test_hf_files_gated_returns_403(client, monkeypatch):
    def gated(repo):
        raise PermissionError('HF 승인이 필요한 모델입니다 - 공개 모델만 지원합니다')

    monkeypatch.setattr(model_router_module.model_service, 'list_hf_gguf_files', gated)
    resp = client.get('/models/hf/files?repo=meta-llama/x')
    assert resp.status_code == 403
    assert 'HF 승인' in resp.get_json()['error']


def test_hf_files_returns_files(client, monkeypatch):
    monkeypatch.setattr(model_router_module.model_service, 'list_hf_gguf_files',
                        lambda repo: [{'filename': 'a-Q4_K_M.gguf', 'quant': 'Q4_K_M'}])
    resp = client.get('/models/hf/files?repo=unsloth/x')
    assert resp.status_code == 200
    assert resp.get_json()['files'][0]['quant'] == 'Q4_K_M'


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
