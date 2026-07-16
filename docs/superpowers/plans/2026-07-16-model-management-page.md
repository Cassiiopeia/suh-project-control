# 모델 관리 페이지 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리 허브에 `/admin/models` 페이지를 추가해 HF 허브의 GGUF 모델을 검색→Ollama로 다운로드(진행률·취소)→설치 목록 관리(삭제)→여러 모델 비교 벤치마크(텍스트·이미지)까지 한 화면에서 수행한다.

**Architecture:** Flask 백엔드에 `model_router.py`(Blueprint) + `model_service.py`(Ollama SDK + HF Hub API 클라이언트)를 추가하고, 프론트는 기존 admin 패턴(DaisyUI + 바닐라 JS + `apiFetch`)의 `models.html` + `models.js`. 텍스트 벤치마크는 기존 `POST /ollama/chat`, 이미지 벤치마크는 기존 `POST /ocr/base64`·`/ocr/url`을 재사용한다.

**Tech Stack:** Flask 3.0, ollama==0.6.1 (Python SDK), requests, pytest(+monkeypatch), DaisyUI, 바닐라 JS

**Spec:** `docs/superpowers/specs/2026-07-16-model-management-page-design.md`

## Global Constraints

- 신규 pip 의존성 추가 금지 — `flask`, `ollama==0.6.1`, `requests`는 이미 `suh-ai-server/flask/requirements.txt`에 있음
- 모든 pytest 실행은 `suh-ai-server/flask/` 디렉토리에서: `python -m pytest test/... -v` (conftest.py가 sys.path를 잡아줌)
- HTML/CSS는 daisyUI native 컴포넌트 우선, 커스텀 CSS 금지, 색상은 다크/라이트 테마 토큰만 사용
- admin 페이지에 이모지 문자 사용 금지 — `test_no_emoji_icons_on_any_admin_page`가 검증함. 아이콘은 lucide(`data-lucide`)만
- JS로 동적 삽입하는 DOM에는 `data-lucide` 아이콘을 넣지 않는다(`lucide.createIcons()` 재호출 필요해짐) — 동적 행의 버튼은 텍스트("삭제", "받기")로
- 템플릿에서 새 lucide 아이콘 사용 전 `static/js/vendor/lucide.min.js`에 해당 아이콘이 있는지 확인(없으면 유사 아이콘으로 대체)
- Ollama 접속은 반드시 `Client(host='http://127.0.0.1:11434')` 명시 생성 — `OLLAMA_HOST` 환경변수(0.0.0.0)에 의존하면 Windows에서 깨짐 (기존 서비스들과 동일 패턴)
- 커밋 메시지는 저장소 컨벤션 `<작업 요약> : <타입> : <설명>` 형식(git log 참고). **커밋 메시지·PR에 AI 관여 흔적(Co-Authored-By: Claude, Generated with Claude Code 등) 절대 금지**
- 신규 백엔드 URL은 `/models/*` 프리픽스(기존 `/ollama/*`, `/ocr/*` 스타일). nginx `/api/flask/` location이 그대로 프록시하므로 nginx 수정 불필요

---

### Task 1: ModelService — HF 허브 검색·GGUF 파일 목록

**Files:**
- Create: `suh-ai-server/flask/service/model_service.py`
- Test: `suh-ai-server/flask/test/test_model_service.py`

**Interfaces:**
- Consumes: 없음 (HF Hub 공개 REST API — `requests`로 호출, 테스트에서는 mock)
- Produces:
  - `ModelService.search_hf_models(query: str, limit: int = 20) -> list` — `[{'repo_id': str, 'downloads': int, 'likes': int, 'updated_at': str|None}]`
  - `ModelService.list_hf_gguf_files(repo_id: str) -> list` — `[{'filename': str, 'size': int|None, 'quant': str|None, 'ollama_name': str}]`, gated 레포(401/403)면 `PermissionError` raise

- [ ] **Step 1: 실패하는 테스트 작성**

`suh-ai-server/flask/test/test_model_service.py` 생성:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run (suh-ai-server/flask 에서): `python -m pytest test/test_model_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'service.model_service'`

- [ ] **Step 3: 최소 구현 작성**

`suh-ai-server/flask/service/model_service.py` 생성:

```python
"""
Model Management Service
HF 허브 검색·GGUF 파일 조회 + Ollama pull/삭제/설치 목록(vision capability 포함)
"""
import json
import logging
import re

import requests
from ollama import Client

logger = logging.getLogger(__name__)

HF_API_BASE = 'https://huggingface.co/api'

# 파일명 끝의 양자화 태그 추출: gemma-3-4b-it-Q4_K_M.gguf → Q4_K_M (IQ4_XS, F16, BF16 등 포함)
_QUANT_RE = re.compile(r'[-.]((?:i?q\d[a-z0-9_]*)|f16|f32|bf16)\.gguf$', re.IGNORECASE)


class ModelService:
    """HF 허브 검색과 Ollama 모델 관리(pull/delete/list)를 담당"""

    def __init__(self, ollama_url: str = 'http://127.0.0.1:11434'):
        self.ollama_url = ollama_url.rstrip('/')
        # 명시적으로 Client를 생성하여 OLLAMA_HOST 환경변수(0.0.0.0)에 의존하지 않음
        self.client = Client(host=self.ollama_url)

    # ---------- Hugging Face ----------

    def search_hf_models(self, query: str, limit: int = 20) -> list:
        """GGUF 필터로 HF 모델 검색 — 다운로드수 내림차순

        Returns:
            [{'repo_id', 'downloads', 'likes', 'updated_at'}, ...]
        """
        resp = requests.get(
            f'{HF_API_BASE}/models',
            params={'search': query, 'filter': 'gguf', 'sort': 'downloads',
                    'direction': -1, 'limit': limit},
            timeout=15,
        )
        resp.raise_for_status()
        return [
            {
                'repo_id': m.get('id'),
                'downloads': m.get('downloads', 0),
                'likes': m.get('likes', 0),
                'updated_at': m.get('lastModified'),
            }
            for m in resp.json()
        ]

    def list_hf_gguf_files(self, repo_id: str) -> list:
        """레포의 GGUF 파일 목록 — 양자화 태그·Ollama pull용 이름 포함

        Raises:
            PermissionError: gated 모델(401/403) — 공개 모델만 지원
        """
        resp = requests.get(f'{HF_API_BASE}/models/{repo_id}/tree/main', timeout=15)
        if resp.status_code in (401, 403):
            raise PermissionError('HF 승인이 필요한 모델입니다 - 공개 모델만 지원합니다')
        resp.raise_for_status()
        files = []
        for entry in resp.json():
            path = entry.get('path', '')
            if not path.lower().endswith('.gguf'):
                continue
            match = _QUANT_RE.search(path)
            quant = match.group(1).upper() if match else None
            files.append({
                'filename': path,
                'size': entry.get('size'),
                'quant': quant,
                # 양자화 태그가 없으면 tag 없이 pull(레포의 기본 GGUF)
                'ollama_name': f'hf.co/{repo_id}:{quant}' if quant else f'hf.co/{repo_id}',
            })
        return files
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_model_service.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/model_service.py suh-ai-server/flask/test/test_model_service.py
git commit -m "모델 관리 페이지 : feat : HF 허브 GGUF 검색·파일목록 서비스 추가"
```

---

### Task 2: ModelService — Ollama 설치 목록(vision)·삭제·pull 스트림

**Files:**
- Modify: `suh-ai-server/flask/service/model_service.py` (Task 1에서 생성한 클래스에 메서드 추가)
- Test: `suh-ai-server/flask/test/test_model_service.py` (테스트 추가)

**Interfaces:**
- Consumes: `ollama.Client` — `.list()`, `.show(name)`(→`.capabilities`), `.delete(name)`, `.pull(name, stream=True)`(→`ProgressResponse(status, total, completed)` 이터레이터)
- Produces:
  - `ModelService.list_installed_models() -> list` — `[{'name', 'size', 'parameter_size', 'quantization', 'family', 'modified_at', 'vision': bool}]` (이름순)
  - `ModelService.delete_model(name: str) -> None`
  - `ModelService.pull_model_stream(name: str)` — NDJSON 라인(`str`) 제너레이터. 진행 라인 `{"status", "total", "completed"}`, 실패 시 `{"error": str}` 한 줄 yield 후 종료

- [ ] **Step 1: 실패하는 테스트 추가**

`test_model_service.py` 끝에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest test/test_model_service.py -v`
Expected: 신규 5개 FAIL — `AttributeError: 'ModelService' object has no attribute 'list_installed_models'`

- [ ] **Step 3: 구현 추가**

`model_service.py`의 `ModelService` 클래스 끝에 추가:

```python
    # ---------- Ollama ----------

    def list_installed_models(self) -> list:
        """설치된 모델 목록 + vision capability (이름순)"""
        response = self.client.list()
        models = []
        for m in response.models:
            details = m.details
            models.append({
                'name': m.model,
                'size': m.size,
                'parameter_size': details.parameter_size if details else None,
                'quantization': details.quantization_level if details else None,
                'family': details.family if details else None,
                'modified_at': m.modified_at.isoformat() if m.modified_at else None,
                'vision': self._has_vision(m.model),
            })
        models.sort(key=lambda x: x['name'] or '')
        return models

    def _has_vision(self, name: str) -> bool:
        """Ollama show의 capabilities에 vision 포함 여부 (조회 실패 시 False)"""
        try:
            info = self.client.show(name)
            return 'vision' in (info.capabilities or [])
        except Exception:
            return False

    def delete_model(self, name: str) -> None:
        """설치된 모델 삭제"""
        self.client.delete(name)

    def pull_model_stream(self, name: str):
        """Ollama pull 진행률 제너레이터 — NDJSON 라인 yield

        클라이언트 연결이 끊기면 WSGI가 제너레이터를 close()하고(GeneratorExit)
        ollama 클라이언트의 HTTP 스트림도 함께 닫혀 다운로드가 중단된다.
        받다 만 레이어는 Ollama가 캐시하므로 재시도 시 이어받는다.
        """
        logger.info(f"Model pull start: {name}")
        try:
            for progress in self.client.pull(name, stream=True):
                yield json.dumps({
                    'status': progress.status,
                    'total': progress.total,
                    'completed': progress.completed,
                }) + '\n'
            logger.info(f"Model pull done: {name}")
        except Exception as e:
            logger.error(f"Model pull failed ({name}): {str(e)}")
            yield json.dumps({'error': str(e)}) + '\n'
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_model_service.py -v`
Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/model_service.py suh-ai-server/flask/test/test_model_service.py
git commit -m "모델 관리 페이지 : feat : Ollama 설치목록(vision)·삭제·pull 진행률 스트림 서비스 추가"
```

---

### Task 3: model_router — /models/* 엔드포인트 + app.py 등록

**Files:**
- Create: `suh-ai-server/flask/router/model_router.py`
- Modify: `suh-ai-server/flask/app.py` (import 2곳 — blueprint import·register)
- Test: `suh-ai-server/flask/test/test_model_router.py`

**Interfaces:**
- Consumes: Task 1·2의 `ModelService` 전체 메서드 (라우터 모듈 레벨 싱글턴 `model_service`)
- Produces (프론트 Task 5가 호출):
  - `GET /models/installed` → `{"success": true, "models": [...]}`
  - `DELETE /models/installed?name=<모델명>` → `{"success": true, "name": ...}` (name 없으면 400)
  - `GET /models/search?q=<검색어>` → `{"success": true, "results": [...]}` (q 없으면 400)
  - `GET /models/hf/files?repo=<repo_id>` → `{"success": true, "repo_id", "files": [...]}` (repo 없으면 400, gated면 403)
  - `POST /models/pull` body `{"name": str}` → NDJSON 스트림, 헤더 `X-Accel-Buffering: no` (name 없으면 400)

- [ ] **Step 1: 실패하는 테스트 작성**

`suh-ai-server/flask/test/test_model_router.py` 생성:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest test/test_model_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'router.model_router'`

- [ ] **Step 3: 라우터 구현**

`suh-ai-server/flask/router/model_router.py` 생성:

```python
"""
Model management router — HF 검색·다운로드(pull)·설치 목록·삭제
관리 페이지(/admin/models)가 사용. 텍스트 테스트는 /ollama/chat, 이미지 테스트는 /ocr/* 재사용.
"""
from flask import Blueprint, Response, jsonify, request
from service.model_service import ModelService
import logging

logger = logging.getLogger(__name__)

model_bp = Blueprint('model', __name__)
model_service = ModelService()


@model_bp.route('/models/installed', methods=['GET'])
def installed_models():
    """설치된 Ollama 모델 목록 (vision capability 포함)"""
    try:
        models = model_service.list_installed_models()
        return jsonify({'success': True, 'models': models}), 200
    except Exception as e:
        logger.error(f"Installed model list failed: {str(e)}")
        return jsonify({'error': f'Ollama connection failed: {str(e)}'}), 500


@model_bp.route('/models/installed', methods=['DELETE'])
def delete_model():
    """설치된 모델 삭제 — 모델명에 /·:가 있어 query parameter 사용"""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name query parameter is required'}), 400
    try:
        model_service.delete_model(name)
        logger.info(f"Model deleted: {name}")
        return jsonify({'success': True, 'name': name}), 200
    except Exception as e:
        logger.error(f"Model delete failed ({name}): {str(e)}")
        return jsonify({'error': f'Model delete failed: {str(e)}'}), 500


@model_bp.route('/models/search', methods=['GET'])
def search_models():
    """HF 허브 GGUF 모델 검색"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'q query parameter is required'}), 400
    try:
        results = model_service.search_hf_models(query)
        return jsonify({'success': True, 'results': results}), 200
    except Exception as e:
        logger.error(f"HF search failed ({query}): {str(e)}")
        return jsonify({'error': f'HF search failed: {str(e)}'}), 500


@model_bp.route('/models/hf/files', methods=['GET'])
def hf_files():
    """HF 레포의 GGUF 파일(양자화별) 목록"""
    repo = request.args.get('repo', '').strip()
    if not repo:
        return jsonify({'error': 'repo query parameter is required'}), 400
    try:
        files = model_service.list_hf_gguf_files(repo)
        return jsonify({'success': True, 'repo_id': repo, 'files': files}), 200
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        logger.error(f"HF file list failed ({repo}): {str(e)}")
        return jsonify({'error': f'HF file list failed: {str(e)}'}), 500


@model_bp.route('/models/pull', methods=['POST'])
def pull_model():
    """모델 다운로드 — Ollama pull 진행률을 NDJSON 스트림으로 중계

    클라이언트가 연결을 끊으면(취소 버튼) 제너레이터가 닫혀 다운로드도 중단된다.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400
    name = data.get('name', '').strip() if isinstance(data.get('name'), str) else ''
    if not name:
        return jsonify({'error': 'name is required'}), 400
    return Response(
        model_service.pull_model_stream(name),
        mimetype='application/x-ndjson',
        headers={
            # nginx 프록시 버퍼링 해제 — 진행률을 실시간 전달
            'X-Accel-Buffering': 'no',
            'Cache-Control': 'no-cache',
        },
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_model_router.py -v`
Expected: 11 passed

- [ ] **Step 5: app.py에 blueprint 등록**

`suh-ai-server/flask/app.py` 수정 — import 블록의 `from router.admin_router import admin_bp` 아래에 추가:

```python
from router.model_router import model_bp
```

register 블록의 `app.register_blueprint(admin_bp)` 아래에 추가:

```python
app.register_blueprint(model_bp)
```

(주의: 현재 app.py에 `ollama_bp` 등록이 이미 있다면 그 형식과 나란히 배치)

- [ ] **Step 6: 전체 테스트로 회귀 확인**

Run: `python -m pytest test/ -v`
Expected: 전부 passed (app import가 깨지지 않았는지 확인)

- [ ] **Step 7: 커밋**

```bash
git add suh-ai-server/flask/router/model_router.py suh-ai-server/flask/app.py suh-ai-server/flask/test/test_model_router.py
git commit -m "모델 관리 페이지 : feat : /models 검색·다운로드·삭제·설치목록 API 추가"
```

---

### Task 4: 관리 페이지 라우트·템플릿·사이드바·대시보드 카드

**Files:**
- Modify: `suh-ai-server/flask/router/admin_router.py` (라우트 1개 추가)
- Create: `suh-ai-server/flask/templates/admin/models.html`
- Modify: `suh-ai-server/flask/templates/admin/base.html` (사이드바 메뉴 1개)
- Modify: `suh-ai-server/flask/templates/admin/dashboard.html` (카드 1개)
- Test: `suh-ai-server/flask/test/test_admin_router.py` (테스트 추가·이모지 검사 경로 추가)

**Interfaces:**
- Consumes: 없음 (렌더링만 — JS는 Task 5)
- Produces: `GET /admin/models` → `models.html` 렌더 (`root='..'`, `active='models'`). 템플릿의 DOM id들은 Task 5의 `models.js`가 사용: `installed-body`, `installed-count`, `installed-refresh`, `installed-error`, `search-input`, `search-btn`, `search-results-wrap`, `search-body`, `files-wrap`, `files-repo`, `files-body`, `pull-wrap`, `pull-name`, `pull-cancel`, `pull-progress`, `pull-status`, `pull-bytes`, `bench-prompt`, `bench-file`, `bench-url`, `bench-models`, `bench-run`, `bench-status`, `bench-current`, `bench-body`, `bench-empty`, `delete-modal`, `delete-model-name`, `delete-confirm`

- [ ] **Step 1: 실패하는 테스트 추가**

`test_admin_router.py`에 추가하고, 이모지 검사 경로에 `/admin/models`를 넣는다:

```python
def test_models_page_renders(client):
    resp = client.get('/admin/models')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '모델 관리' in body
    assert 'installed-body' in body
    assert 'bench-run' in body
    assert 'delete-modal' in body
```

기존 `test_no_emoji_icons_on_any_admin_page`의 튜플 수정:

```python
    for path in ('/admin', '/admin/palworld', '/admin/logs', '/admin/models'):
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest test/test_admin_router.py -v`
Expected: `test_models_page_renders` FAIL (404)

- [ ] **Step 3: 라우트 추가**

`admin_router.py` 끝에 추가:

```python
@admin_bp.route('/admin/models', methods=['GET'])
def models():
    """모델 관리 페이지 (HF 검색·다운로드·벤치마크)"""
    return render_template('admin/models.html', root='..', active='models')
```

- [ ] **Step 4: 템플릿 작성**

`suh-ai-server/flask/templates/admin/models.html` 생성:

```html
{% extends "admin/base.html" %}
{% block title %}모델 관리 | SUH AI Server{% endblock %}
{% block page_title %}모델 관리{% endblock %}
{% block content %}
<div class="space-y-6 max-w-6xl mx-auto">

  <!-- 설치된 모델 -->
  <div class="card bg-base-100 shadow">
    <div class="card-body">
      <div class="flex items-center justify-between">
        <h2 class="card-title text-base">
          <i data-lucide="hard-drive" class="size-5 text-primary"></i>설치된 모델
          <span id="installed-count" class="badge badge-ghost badge-sm">0</span>
        </h2>
        <button id="installed-refresh" class="btn btn-ghost btn-sm" title="새로고침">
          <i data-lucide="refresh-cw" class="size-4"></i>
        </button>
      </div>
      <div id="installed-error" class="alert alert-error hidden">
        <span>Ollama 서버에 연결할 수 없습니다.</span>
      </div>
      <div class="overflow-x-auto">
        <table class="table table-sm">
          <thead>
            <tr><th>이름</th><th>크기</th><th>패밀리</th><th>파라미터</th><th>양자화</th><th>수정일</th><th></th></tr>
          </thead>
          <tbody id="installed-body">
            <tr><td colspan="7" class="text-center opacity-60">불러오는 중...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- HF 검색·다운로드 -->
  <div class="card bg-base-100 shadow">
    <div class="card-body">
      <h2 class="card-title text-base">
        <i data-lucide="search" class="size-5 text-primary"></i>Hugging Face 모델 검색
      </h2>
      <div class="join w-full max-w-md">
        <input id="search-input" class="input input-sm join-item flex-1"
               placeholder="예: gemma, qwen vl, ocr">
        <button id="search-btn" class="btn btn-primary btn-sm join-item">검색</button>
      </div>
      <p class="text-xs opacity-60">
        GGUF 형식 공개 모델만 검색됩니다. gated 모델(승인 필요)은 지원하지 않습니다.
        vision 모델은 레포 구조에 따라 가져오기가 실패할 수 있습니다.
      </p>

      <div id="search-results-wrap" class="overflow-x-auto hidden">
        <table class="table table-sm">
          <thead><tr><th>레포 (클릭해서 파일 보기)</th><th>다운로드</th><th>좋아요</th><th>업데이트</th></tr></thead>
          <tbody id="search-body"></tbody>
        </table>
      </div>

      <div id="files-wrap" class="hidden">
        <h3 class="font-semibold text-sm mt-2">
          <span id="files-repo" class="font-mono"></span> 의 GGUF 파일
        </h3>
        <div class="overflow-x-auto">
          <table class="table table-sm">
            <thead><tr><th>파일</th><th>양자화</th><th>크기</th><th></th></tr></thead>
            <tbody id="files-body"></tbody>
          </table>
        </div>
      </div>

      <!-- 다운로드 진행률 -->
      <div id="pull-wrap" class="hidden border border-base-300 rounded-lg p-3 space-y-2">
        <div class="flex items-center justify-between">
          <span id="pull-name" class="text-sm font-mono"></span>
          <button id="pull-cancel" class="btn btn-error btn-xs">취소</button>
        </div>
        <progress id="pull-progress" class="progress progress-primary w-full" value="0" max="100"></progress>
        <div class="flex justify-between text-xs opacity-70">
          <span id="pull-status">준비 중...</span>
          <span id="pull-bytes"></span>
        </div>
      </div>
    </div>
  </div>

  <!-- 테스트·벤치마크 -->
  <div class="card bg-base-100 shadow">
    <div class="card-body">
      <h2 class="card-title text-base">
        <i data-lucide="flask-conical" class="size-5 text-primary"></i>테스트 · 벤치마크
      </h2>
      <p class="text-xs opacity-60">
        같은 입력을 선택한 모델들에 순차 실행해 결과와 응답 시간을 비교합니다.
        이미지를 첨부하면 vision 모델만 선택할 수 있습니다. 모델 1개만 선택하면 단일 테스트입니다.
      </p>

      <fieldset class="fieldset w-full">
        <legend class="fieldset-legend">프롬프트 (필수)</legend>
        <textarea id="bench-prompt" class="textarea textarea-sm w-full" rows="2"
                  placeholder="예: Extract all text from this image / 한국의 수도는?"></textarea>
      </fieldset>

      <div class="flex flex-wrap gap-4">
        <fieldset class="fieldset">
          <legend class="fieldset-legend">이미지 파일 (선택)</legend>
          <input id="bench-file" type="file" accept="image/*" class="file-input file-input-sm w-72">
        </fieldset>
        <fieldset class="fieldset">
          <legend class="fieldset-legend">또는 이미지 URL (선택)</legend>
          <input id="bench-url" class="input input-sm w-72" placeholder="https://...">
        </fieldset>
      </div>

      <fieldset class="fieldset w-full">
        <legend class="fieldset-legend">모델 선택</legend>
        <div id="bench-models" class="flex flex-wrap gap-2">
          <span class="text-sm opacity-60">설치된 모델을 불러오는 중...</span>
        </div>
      </fieldset>

      <div class="card-actions items-center">
        <button id="bench-run" class="btn btn-primary btn-sm">
          <i data-lucide="play" class="size-4"></i>실행
        </button>
        <span id="bench-status" class="text-sm opacity-70 hidden">
          <span class="loading loading-spinner loading-xs"></span>
          <span id="bench-current"></span> 실행 중...
        </span>
      </div>

      <div class="overflow-x-auto">
        <table class="table table-sm">
          <thead><tr><th>모델</th><th>상태</th><th>시간</th><th>결과</th></tr></thead>
          <tbody id="bench-body">
            <tr id="bench-empty"><td colspan="4" class="text-center opacity-60">아직 실행한 벤치마크가 없습니다.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- 삭제 확인 모달 -->
<dialog id="delete-modal" class="modal">
  <div class="modal-box">
    <h3 class="font-bold text-lg flex items-center gap-2">
      <i data-lucide="trash-2" class="size-5 text-error"></i>모델 삭제
    </h3>
    <p class="py-3 text-sm">
      <span id="delete-model-name" class="font-mono font-semibold"></span> 모델을 삭제할까요?
      디스크에서 제거되며 다시 사용하려면 재다운로드해야 합니다.
    </p>
    <div class="modal-action">
      <form method="dialog"><button class="btn btn-ghost btn-sm">취소</button></form>
      <button id="delete-confirm" class="btn btn-error btn-sm">삭제</button>
    </div>
  </div>
  <form method="dialog" class="modal-backdrop"><button>close</button></form>
</dialog>
{% endblock %}
{% block extra_js %}
<script src="{{ root }}/static/js/models.js?v={{ asset('js/models.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: 사이드바·대시보드 카드 추가**

`base.html` — `Ollama 테스트` `<li>` 항목 바로 아래에 추가:

```html
        <li>
          <a href="{{ root }}/admin/models" class="{{ 'menu-active' if active == 'models' else '' }}">
            <i data-lucide="package" class="size-5"></i>모델 관리
          </a>
        </li>
```

`dashboard.html` — `Ollama 테스트` 카드 `</a>` 바로 아래에 추가:

```html
    <a href="./admin/models" class="card bg-base-100 shadow-md hover:shadow-xl transition-shadow">
      <div class="card-body">
        <h2 class="card-title text-base">
          <i data-lucide="package" class="size-5 text-primary"></i>모델 관리
        </h2>
        <p class="text-sm opacity-70">HF GGUF 검색 · 다운로드 · 모델 벤치마크</p>
      </div>
    </a>
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest test/test_admin_router.py -v`
Expected: 전부 passed (이모지 검사 포함)

- [ ] **Step 7: 커밋**

```bash
git add suh-ai-server/flask/router/admin_router.py suh-ai-server/flask/templates/admin/models.html suh-ai-server/flask/templates/admin/base.html suh-ai-server/flask/templates/admin/dashboard.html suh-ai-server/flask/test/test_admin_router.py
git commit -m "모델 관리 페이지 : feat : /admin/models 페이지·사이드바·대시보드 카드 추가"
```

---

### Task 5: models.js — 설치 목록·검색·다운로드(진행률/취소)·벤치마크

**Files:**
- Create: `suh-ai-server/flask/static/js/models.js`

**Interfaces:**
- Consumes:
  - Task 3의 `/models/*` API 전부
  - 기존 `POST /ollama/chat` (`{model, prompt}` → `{content, metrics.total_duration_ms}`)
  - 기존 `POST /ocr/base64` (`{image_base64, prompt, model}` → `{result}`), `POST /ocr/url` (`{image_url, prompt, model}` → `{result}`)
  - `admin-common.js`의 전역 `apiFetch(path, options)`(X-API-Key 자동 첨부, 401 시 모달), `showToast(msg, type)`, `escapeHtml(v)`
  - Task 4 템플릿의 DOM id 전부
- Produces: 없음 (최종 소비자)

기존 JS(단위 테스트 없음) 패턴과 동일하게 이 파일은 pytest 대상이 아니다. 검증은 Task 4의 렌더 테스트 + Task 6의 수동 검증으로 한다.

- [ ] **Step 1: 파일 작성**

`suh-ai-server/flask/static/js/models.js` 생성:

```javascript
/* 모델 관리 페이지 로직. base: /admin/models → API는 ../models/*, ../ollama/*, ../ocr/* */
const MODELS_API = '../models';

let installedModels = [];   // GET /models/installed 결과 캐시
let pullController = null;  // 진행 중 pull의 AbortController (동시 1건만 허용)
let pullErrorMessage = null;
let benchRunning = false;
let deleteTarget = null;

function el(id) { return document.getElementById(id); }

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return '-';
  const gb = bytes / 1024 / 1024 / 1024;
  if (gb >= 1) return gb.toFixed(1) + 'GB';
  return (bytes / 1024 / 1024).toFixed(0) + 'MB';
}

/* ---------- 설치된 모델 ---------- */
async function loadInstalled() {
  const body = el('installed-body');
  try {
    const resp = await apiFetch(MODELS_API + '/installed');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '조회 실패');
    installedModels = data.models;
    el('installed-error').classList.add('hidden');
    renderInstalled();
    renderBenchModels();
  } catch (e) {
    el('installed-error').classList.remove('hidden');
    body.innerHTML = '<tr><td colspan="7" class="text-center opacity-60">조회 실패</td></tr>';
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('설치 모델 조회 실패: ' + e.message, 'error');
    }
  }
}

function renderInstalled() {
  const body = el('installed-body');
  el('installed-count').textContent = installedModels.length;
  if (!installedModels.length) {
    body.innerHTML = '<tr><td colspan="7" class="text-center opacity-60">설치된 모델이 없습니다. 아래에서 검색해 받아보세요.</td></tr>';
    return;
  }
  body.innerHTML = installedModels.map(function (m) {
    const vision = m.vision ? ' <span class="badge badge-info badge-xs">vision</span>' : '';
    return '<tr>'
      + '<td class="font-mono">' + escapeHtml(m.name) + vision + '</td>'
      + '<td>' + fmtSize(m.size) + '</td>'
      + '<td>' + escapeHtml(m.family || '-') + '</td>'
      + '<td>' + escapeHtml(m.parameter_size || '-') + '</td>'
      + '<td>' + escapeHtml(m.quantization || '-') + '</td>'
      + '<td>' + (m.modified_at ? escapeHtml(m.modified_at.slice(0, 10)) : '-') + '</td>'
      + '<td><button class="btn btn-error btn-xs" data-delete="' + escapeHtml(m.name) + '">삭제</button></td>'
      + '</tr>';
  }).join('');
  body.querySelectorAll('[data-delete]').forEach(function (btn) {
    btn.addEventListener('click', function () { openDeleteModal(btn.dataset.delete); });
  });
}

function openDeleteModal(name) {
  deleteTarget = name;
  el('delete-model-name').textContent = name;
  el('delete-modal').showModal();
}

async function doDelete() {
  if (!deleteTarget) return;
  try {
    const resp = await apiFetch(MODELS_API + '/installed?name=' + encodeURIComponent(deleteTarget), { method: 'DELETE' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '삭제 실패');
    showToast(deleteTarget + ' 삭제 완료', 'success');
  } catch (e) {
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('삭제 실패: ' + e.message, 'error');
    }
  } finally {
    el('delete-modal').close();
    deleteTarget = null;
    loadInstalled();
  }
}

/* ---------- HF 검색 ---------- */
async function searchHf() {
  const q = el('search-input').value.trim();
  if (!q) { showToast('검색어를 입력하세요', 'warning'); return; }
  const body = el('search-body');
  el('search-results-wrap').classList.remove('hidden');
  el('files-wrap').classList.add('hidden');
  body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">검색 중...</td></tr>';
  try {
    const resp = await apiFetch(MODELS_API + '/search?q=' + encodeURIComponent(q));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '검색 실패');
    if (!data.results.length) {
      body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">결과 없음</td></tr>';
      return;
    }
    body.innerHTML = data.results.map(function (r) {
      return '<tr class="cursor-pointer hover" data-repo="' + escapeHtml(r.repo_id) + '">'
        + '<td class="font-mono">' + escapeHtml(r.repo_id) + '</td>'
        + '<td>' + (r.downloads || 0).toLocaleString() + '</td>'
        + '<td>' + (r.likes || 0) + '</td>'
        + '<td>' + (r.updated_at ? escapeHtml(r.updated_at.slice(0, 10)) : '-') + '</td>'
        + '</tr>';
    }).join('');
    body.querySelectorAll('[data-repo]').forEach(function (row) {
      row.addEventListener('click', function () { loadFiles(row.dataset.repo); });
    });
  } catch (e) {
    body.innerHTML = '<tr><td colspan="4" class="text-center text-error">검색 실패</td></tr>';
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('HF 검색 실패: ' + e.message, 'error');
    }
  }
}

async function loadFiles(repoId) {
  const body = el('files-body');
  el('files-wrap').classList.remove('hidden');
  el('files-repo').textContent = repoId;
  body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">파일 조회 중...</td></tr>';
  try {
    const resp = await apiFetch(MODELS_API + '/hf/files?repo=' + encodeURIComponent(repoId));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '파일 조회 실패');
    if (!data.files.length) {
      body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">GGUF 파일이 없습니다</td></tr>';
      return;
    }
    body.innerHTML = data.files.map(function (f) {
      return '<tr>'
        + '<td class="font-mono text-xs">' + escapeHtml(f.filename) + '</td>'
        + '<td>' + escapeHtml(f.quant || '-') + '</td>'
        + '<td>' + fmtSize(f.size) + '</td>'
        + '<td><button class="btn btn-primary btn-xs" data-pull="' + escapeHtml(f.ollama_name) + '">받기</button></td>'
        + '</tr>';
    }).join('');
    body.querySelectorAll('[data-pull]').forEach(function (btn) {
      btn.addEventListener('click', function () { startPull(btn.dataset.pull); });
    });
  } catch (e) {
    body.innerHTML = '<tr><td colspan="4" class="text-center text-error">' + escapeHtml(e.message) + '</td></tr>';
  }
}

/* ---------- 다운로드 (pull) ---------- */
async function startPull(name) {
  if (pullController) { showToast('이미 다운로드가 진행 중입니다', 'warning'); return; }
  pullController = new AbortController();
  pullErrorMessage = null;
  el('pull-wrap').classList.remove('hidden');
  el('pull-name').textContent = name;
  el('pull-status').textContent = '시작 중...';
  el('pull-bytes').textContent = '';
  el('pull-progress').value = 0;

  try {
    const resp = await apiFetch(MODELS_API + '/pull', {
      method: 'POST',
      body: JSON.stringify({ name: name }),
      signal: pullController.signal,
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.error || 'HTTP ' + resp.status);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.filter(Boolean).forEach(function (line) {
        try { handlePullLine(JSON.parse(line)); } catch (e) { /* 불완전 라인 무시 */ }
      });
    }
    if (pullErrorMessage) {
      showToast('다운로드 실패: ' + pullErrorMessage
        + ' — 이 레포는 Ollama 직접 가져오기를 지원하지 않는 구조일 수 있습니다', 'error');
    } else {
      showToast(name + ' 다운로드 완료', 'success');
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      showToast('다운로드를 취소했습니다. 다시 받으면 이어서 받습니다.', 'info');
    } else if (e.message.indexOf('Unauthorized') === -1) {
      showToast('다운로드 실패: ' + e.message, 'error');
    }
  } finally {
    pullController = null;
    el('pull-wrap').classList.add('hidden');
    loadInstalled();
  }
}

function handlePullLine(p) {
  if (p.error) { pullErrorMessage = p.error; return; }
  el('pull-status').textContent = p.status || '';
  if (p.total) {
    const percent = p.completed ? Math.round((p.completed / p.total) * 100) : 0;
    el('pull-progress').value = percent;
    el('pull-bytes').textContent = fmtSize(p.completed || 0) + ' / ' + fmtSize(p.total) + ' (' + percent + '%)';
  }
}

function cancelPull() {
  if (pullController) pullController.abort();
}

/* ---------- 테스트·벤치마크 ---------- */
function hasImageInput() {
  return !!(el('bench-file').files.length || el('bench-url').value.trim());
}

function renderBenchModels() {
  const wrap = el('bench-models');
  if (!installedModels.length) {
    wrap.innerHTML = '<span class="text-sm opacity-60">설치된 모델이 없습니다</span>';
    return;
  }
  const imageMode = hasImageInput();
  wrap.innerHTML = installedModels.map(function (m) {
    const disabled = imageMode && !m.vision;
    return '<label class="label cursor-pointer gap-2 border border-base-300 rounded-lg px-3 py-1'
      + (disabled ? ' opacity-40' : '') + '">'
      + '<input type="checkbox" class="checkbox checkbox-sm" value="' + escapeHtml(m.name) + '"'
      + (disabled ? ' disabled' : '') + '>'
      + '<span class="font-mono text-sm">' + escapeHtml(m.name) + '</span>'
      + (m.vision ? '<span class="badge badge-info badge-xs">vision</span>' : '')
      + '</label>';
  }).join('');
}

function fileToBase64(file) {
  return new Promise(function (resolve, reject) {
    const reader = new FileReader();
    reader.onload = function () { resolve(String(reader.result).split(',')[1]); };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function runBenchmark() {
  if (benchRunning) return;
  const prompt = el('bench-prompt').value.trim();
  if (!prompt) { showToast('프롬프트를 입력하세요', 'warning'); return; }
  const selected = Array.from(el('bench-models').querySelectorAll('input:checked'))
    .map(function (c) { return c.value; });
  if (!selected.length) { showToast('모델을 하나 이상 선택하세요', 'warning'); return; }

  let imageBase64 = null;
  const imageUrl = el('bench-url').value.trim();
  if (el('bench-file').files.length) {
    imageBase64 = await fileToBase64(el('bench-file').files[0]);
  }

  benchRunning = true;
  el('bench-run').disabled = true;
  el('bench-status').classList.remove('hidden');
  const empty = el('bench-empty');
  if (empty) empty.remove();

  /* 모델을 한 번에 하나씩 순차 실행 — 동시 로드로 인한 서버 메모리 폭주 방지 */
  for (const name of selected) {
    el('bench-current').textContent = name;
    const row = addBenchRow(name);
    const startedAt = performance.now();
    try {
      let resultText;
      let durationMs;
      if (imageBase64) {
        const resp = await apiFetch('../ocr/base64', {
          method: 'POST',
          body: JSON.stringify({ image_base64: imageBase64, prompt: prompt, model: name }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
        resultText = data.result;
        durationMs = performance.now() - startedAt;
      } else if (imageUrl) {
        const resp = await apiFetch('../ocr/url', {
          method: 'POST',
          body: JSON.stringify({ image_url: imageUrl, prompt: prompt, model: name }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
        resultText = data.result;
        durationMs = performance.now() - startedAt;
      } else {
        const resp = await apiFetch('../ollama/chat', {
          method: 'POST',
          body: JSON.stringify({ model: name, prompt: prompt }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
        resultText = data.content;
        durationMs = (data.metrics && data.metrics.total_duration_ms) || (performance.now() - startedAt);
      }
      finishBenchRow(row, true, durationMs, resultText);
    } catch (e) {
      if (e.message.indexOf('Unauthorized') !== -1) { finishBenchRow(row, false, 0, '인증 필요'); break; }
      /* 한 모델 실패해도 다음 모델 계속 */
      finishBenchRow(row, false, performance.now() - startedAt, e.message);
    }
  }

  benchRunning = false;
  el('bench-run').disabled = false;
  el('bench-status').classList.add('hidden');
}

function addBenchRow(name) {
  const row = document.createElement('tr');
  row.innerHTML = '<td class="font-mono">' + escapeHtml(name) + '</td>'
    + '<td><span class="loading loading-spinner loading-xs"></span></td>'
    + '<td>-</td><td class="opacity-60">실행 중...</td>';
  el('bench-body').prepend(row);
  return row;
}

function finishBenchRow(row, ok, durationMs, text) {
  const cells = row.querySelectorAll('td');
  cells[1].innerHTML = ok
    ? '<span class="badge badge-success badge-sm">성공</span>'
    : '<span class="badge badge-error badge-sm">실패</span>';
  cells[2].textContent = (durationMs / 1000).toFixed(1) + 's';
  cells[3].innerHTML = '<pre class="text-xs whitespace-pre-wrap max-w-xl'
    + (ok ? '' : ' text-error') + '">' + escapeHtml(text || '') + '</pre>';
}

/* ---------- 초기화 ---------- */
document.addEventListener('DOMContentLoaded', function () {
  loadInstalled();
  el('installed-refresh').addEventListener('click', loadInstalled);
  el('search-btn').addEventListener('click', searchHf);
  el('search-input').addEventListener('keydown', function (e) { if (e.key === 'Enter') searchHf(); });
  el('pull-cancel').addEventListener('click', cancelPull);
  el('delete-confirm').addEventListener('click', doDelete);
  el('bench-run').addEventListener('click', runBenchmark);
  el('bench-file').addEventListener('change', renderBenchModels);
  el('bench-url').addEventListener('input', renderBenchModels);
});
```

- [ ] **Step 2: 페이지 렌더 테스트로 회귀 확인**

Run: `python -m pytest test/test_admin_router.py -v`
Expected: 전부 passed (asset() 헬퍼가 models.js 수정시각을 잡는지 — 파일이 존재하므로 '0'이 아닌 토큰)

- [ ] **Step 3: 커밋**

```bash
git add suh-ai-server/flask/static/js/models.js
git commit -m "모델 관리 페이지 : feat : 검색·다운로드 진행률/취소·삭제·벤치마크 프론트 로직 추가"
```

---

### Task 6: 하드코딩 모델 목록 제거 + 전체 검증

**Files:**
- Modify: `suh-ai-server/flask/config/app_config.py` (`SUPPORTED_MODELS`·`SUPPORTED_VISION_MODELS` 삭제)

**Interfaces:**
- Consumes: 없음
- Produces: 없음 — grep으로 두 상수를 참조하는 코드가 없음을 이미 확인함(정의만 존재). `DEFAULT_MODEL`·`DEFAULT_VISION_MODEL`·`DEFAULT_PROMPT`·`DEFAULT_VISION_PROMPT`는 유지

- [ ] **Step 1: 참조 없음 재확인**

Run (suh-ai-server/flask 에서): `grep -rn "SUPPORTED_MODELS\|SUPPORTED_VISION_MODELS" --include="*.py" .`
Expected: `config/app_config.py`의 정의 2곳만 출력

- [ ] **Step 2: 목록 삭제**

`config/app_config.py`에서 `SUPPORTED_MODELS = [...]` 블록(주석 포함)과 `SUPPORTED_VISION_MODELS = [...]` 블록(주석 포함)을 삭제한다. 남는 내용:

```python
"""
Flask application configuration
"""

# Swagger UI configuration
SWAGGER_URL = '/api/flask/docs/swagger'
API_URL = '/api/flask/docs/swagger.json'

# Default OCR settings
DEFAULT_PROMPT = 'Extract all text from this image'
DEFAULT_MODEL = 'deepseek-ocr'

# Default Vision settings
DEFAULT_VISION_PROMPT = '이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘.'
DEFAULT_VISION_MODEL = 'gemma3:4b'
```

(설치 모델 목록이 필요한 곳은 이제 `GET /models/installed`가 동적으로 제공)

- [ ] **Step 3: 전체 테스트 실행**

Run: `python -m pytest test/ -v`
Expected: 전부 passed

- [ ] **Step 4: 커밋**

```bash
git add suh-ai-server/flask/config/app_config.py
git commit -m "모델 관리 페이지 : refactor : 하드코딩 SUPPORTED_MODELS 목록 제거 (동적 조회로 대체)"
```

---

## 수동 검증 체크리스트 (구현 완료 후 실서버에서)

spec 7절의 검증 항목 — 자동화 불가, 배포 후 사람이 확인:

1. `/admin/models` 접속 → 설치 모델 목록·vision 뱃지 표시 확인
2. HF 검색 → 텍스트 GGUF 레포(예: `unsloth/Qwen3-0.6B-GGUF`) 양자화 선택 → 다운로드 진행률 실시간 표시 확인
3. 다운로드 중 취소 → 중단 확인 → 같은 모델 재다운로드 시 이어받기 확인
4. vision GGUF 레포 2~3개 pull 시도 → 성공/실패 케이스와 실패 안내 문구 확인 (nginx 뒤에서 진행률이 실시간으로 오는지 — `X-Accel-Buffering` 동작 확인 포함)
5. 벤치마크: 텍스트 모델 2개+프롬프트만 → 순차 실행·시간 비교 확인 / 이미지 첨부 → 비-vision 모델 비활성화 확인 → vision 모델로 OCR 결과 확인
6. 설치 모델 삭제 → 확인 모달 → 목록에서 제거 확인
