"""test_model_router.py — /models/* 엔드포인트 동작 검증 (서비스는 mock)"""
import json

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


def test_pull_requires_name(client):
    assert client.post('/models/pull', json={}).status_code == 400


def test_pull_streams_ndjson_with_no_buffering_header(client, monkeypatch):
    def fake_stream(name):
        yield json.dumps({'status': 'pulling manifest'}) + '\n'
        yield json.dumps({'status': 'success'}) + '\n'

    monkeypatch.setattr(model_router_module.model_service, 'pull_model_stream', fake_stream)
    resp = client.post('/models/pull', json={'name': 'hf.co/unsloth/x:Q4_K_M'})
    assert resp.status_code == 200
    assert resp.headers['X-Accel-Buffering'] == 'no'
    lines = [json.loads(line) for line in resp.get_data(as_text=True).strip().split('\n')]
    assert lines[0]['status'] == 'pulling manifest'
    assert lines[-1]['status'] == 'success'
