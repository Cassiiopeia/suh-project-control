"""ollama_router 단위 테스트 — Ollama 호출은 서비스 레벨에서 모킹"""
import pytest

from app import app as flask_app
from router import ollama_router


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def mock_service(monkeypatch):
    """ollama_service의 외부 호출을 가짜 구현으로 대체"""
    calls = {}

    def fake_list_models():
        return [{'name': 'gemma3:4b', 'size': 3338801718, 'parameter_size': '4.3B', 'family': 'gemma3'}]

    def fake_chat(model, prompt, system=None, temperature=0.0, format_spec=None, auto_unload=False):
        calls['chat'] = {
            'model': model, 'prompt': prompt, 'system': system,
            'temperature': temperature, 'format_spec': format_spec,
            'auto_unload': auto_unload,
        }
        return {
            'content': '{"title":"t","steps":[]}',
            'metrics': {
                'total_duration_ms': 2100.0, 'load_duration_ms': 40.0,
                'prompt_eval_count': 25, 'eval_count': 71,
                'eval_duration_ms': 1900.0, 'tokens_per_second': 37.4,
            },
        }

    monkeypatch.setattr(ollama_router.ollama_service, 'list_models', fake_list_models)
    monkeypatch.setattr(ollama_router.ollama_service, 'chat', fake_chat)
    return calls


def test_list_models(client, mock_service):
    resp = client.get('/ollama/models')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['models'][0]['name'] == 'gemma3:4b'


def test_chat_with_schema(client, mock_service):
    schema = {'type': 'object', 'properties': {'title': {'type': 'string'}}, 'required': ['title']}
    resp = client.post('/ollama/chat', json={
        'model': 'gemma3:4b',
        'prompt': '테스트',
        'system': '시스템',
        'temperature': 0.5,
        'format': schema,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['model'] == 'gemma3:4b'
    assert data['metrics']['tokens_per_second'] == 37.4
    # 파라미터가 서비스까지 그대로 전달되는지
    assert mock_service['chat']['format_spec'] == schema
    assert mock_service['chat']['system'] == '시스템'
    assert mock_service['chat']['temperature'] == 0.5


def test_chat_format_json_string(client, mock_service):
    resp = client.post('/ollama/chat', json={'model': 'gemma3:4b', 'prompt': 'p', 'format': 'json'})
    assert resp.status_code == 200
    assert mock_service['chat']['format_spec'] == 'json'


def test_chat_format_omitted(client, mock_service):
    resp = client.post('/ollama/chat', json={'model': 'gemma3:4b', 'prompt': 'p'})
    assert resp.status_code == 200
    assert mock_service['chat']['format_spec'] is None


@pytest.mark.parametrize('body,expected_error', [
    ({'prompt': 'p'}, 'model is required'),
    ({'model': 'm'}, 'prompt is required'),
    ({'model': 'm', 'prompt': 'p', 'format': 'yaml'}, 'format must be'),
    ({'model': 'm', 'prompt': 'p', 'format': [1, 2]}, 'format must be'),
    ({'model': 'm', 'prompt': 'p', 'temperature': 'hot'}, 'temperature must be'),
])
def test_chat_validation_errors(client, mock_service, body, expected_error):
    resp = client.post('/ollama/chat', json=body)
    assert resp.status_code == 400
    assert expected_error in resp.get_json()['error']
    assert 'chat' not in mock_service  # 서비스 호출 없이 거부


def test_chat_ollama_failure(client, monkeypatch):
    def boom(**kwargs):
        raise Exception('connection refused')
    monkeypatch.setattr(ollama_router.ollama_service, 'chat', boom)
    resp = client.post('/ollama/chat', json={'model': 'm', 'prompt': 'p'})
    assert resp.status_code == 500
    assert 'connection refused' in resp.get_json()['error']


def test_admin_page_renders(client):
    resp = client.get('/admin/ollama-test')
    assert resp.status_code == 200
    assert 'Structured Output'.encode() in resp.data
