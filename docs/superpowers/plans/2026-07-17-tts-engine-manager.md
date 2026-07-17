# TTS 엔진 매니저 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 화면에서 여러 TTS 엔진(Kokoro, CosyVoice)을 설치·전환·테스트하고, 외부에는 `POST /tts` REST API로 음성 합성을 제공한다.

**Architecture:** Flask(Windows 네이티브, NSSM)가 docker CLI subprocess로 TTS 엔진 컨테이너들을 제어한다(palworld_service의 NSSM 제어 패턴 재사용). 엔진별 API 형식 차이는 어댑터 계층이 `synthesize(text, voice, speed) → WAV bytes`로 통일한다. VRAM 8GB 보호를 위해 한 번에 1개 엔진만 실행한다.

**Tech Stack:** Flask + Blueprint, requests, subprocess(docker CLI), pytest(monkeypatch), DaisyUI 관리자 템플릿, GitHub Actions + PowerShell 배포

**Spec:** `docs/superpowers/specs/2026-07-17-tts-engine-manager-design.md`

## Global Constraints

- 모든 응답·주석은 **한국어** (실무 수준의 간결한 WHY 중심 주석)
- 커밋 메시지에 **Co-Authored-By 태그 금지**. 커밋 형식: `TTS 엔진 매니저 : <type> : <설명>`
- **git push는 사용자 명시 허락 시에만** — 각 Task는 로컬 커밋까지만 수행
- GitHub 작업(시크릿 등록 등)은 gh CLI 금지 → `/cassiiopeia:suh-github` 스킬 사용
- 어댑터 공통 인터페이스: `synthesize(text: str, voice: str, speed: float) -> bytes(WAV)`, `health() -> bool`, `voices() -> list`
- 엔진 실행 정책: **한 번에 1개만 실행** (다른 엔진 시작 시 기존 실행 엔진 자동 중지)
- 포트/이름 고정값: Kokoro `suh-tts-kokoro`:8880 (`ghcr.io/remsky/kokoro-fastapi-gpu:latest`), CosyVoice `suh-tts-cosyvoice`:50000 (`cassiiopeia/suh-tts-cosyvoice:latest`), 모델 캐시 볼륨 `suh-tts-models`
- CosyVoice 모델: 초기값 `iic/CosyVoice2-0.5B` (공식 server.py의 문서화된 기본값·한국어 지원). 스펙에 언급된 Fun-CosyVoice3 전환은 컨테이너 env `MODEL_DIR` 교체만으로 가능 — 서버 스모크 테스트(Task 9)에서 시도
- 테스트 실행 위치: `suh-ai-server/flask` 디렉토리에서 `python3 -m pytest test/<파일> -v`
- 사용자가 직접 할 일은 단 하나: **DockerHub 액세스 토큰 제공** (Task 8에서 요청)

## File Structure

```
suh-ai-server/
├─ flask/
│  ├─ config/tts_config.py            # [신규] 엔진 레지스트리 (카탈로그)
│  ├─ service/tts/__init__.py         # [신규] 패키지
│  ├─ service/tts/adapters.py         # [신규] Kokoro/CosyVoice 어댑터
│  ├─ service/tts_service.py          # [신규] 엔진 수명주기 (docker CLI)
│  ├─ service/audit_service.py        # [수정] TTS 카테고리·액션 추가
│  ├─ router/tts_router.py            # [신규] /tts, /tts/engines/*
│  ├─ router/tts_swagger.py           # [신규] Swagger 경로 정의
│  ├─ router/swagger_router.py        # [수정] TTS 경로 병합
│  ├─ router/admin_router.py          # [수정] /admin/tts 페이지
│  ├─ app.py                          # [수정] tts_bp 등록
│  ├─ templates/admin/base.html       # [수정] 사이드바 메뉴
│  ├─ templates/admin/tts.html        # [신규] 관리 페이지
│  ├─ static/js/tts.js                # [신규] 페이지 로직
│  ├─ static/tts-refs/                # [신규] 제로샷 레퍼런스 음성 (CosyVoice 레포 Apache-2.0 자산)
│  └─ test/test_tts_{config,adapters,service,router}.py  # [신규]
├─ docker/cosyvoice/Dockerfile        # [신규] CosyVoice 서빙 이미지
└─ scripts/deploy-tts.ps1             # [신규] GPU 검증 + 볼륨 준비
.github/workflows/
├─ SUH-AI-TTS-IMAGE.yaml              # [신규] CosyVoice 이미지 빌드·push
└─ SUH-AI-PROJECT-CONTROL.yaml        # [수정] deploy-tts 단계 추가
```

---

### Task 1: 엔진 레지스트리 + 레퍼런스 음성 자산

**Files:**
- Create: `suh-ai-server/flask/config/tts_config.py`
- Create: `suh-ai-server/flask/static/tts-refs/ref_a.wav`, `ref_b.wav` (다운로드)
- Test: `suh-ai-server/flask/test/test_tts_config.py`

**Interfaces:**
- Produces: `TTS_ENGINES: dict[str, dict]` — 키: `name, description, image, container, port, adapter, languages, vram, docker_args, command, voices` (+cosyvoice만 `sample_rate`). `voices` 항목: `{'id', 'name'}` (+cosyvoice만 `'file'`)
- Produces: `TTS_REFS_DIR: str` — 레퍼런스 wav 디렉토리 절대경로

- [ ] **Step 1: 레퍼런스 음성 다운로드**

CosyVoice 공식 레포(Apache-2.0)의 제로샷 프롬프트 샘플을 받는다:

```bash
cd suh-ai-server/flask
mkdir -p static/tts-refs
curl -L -o static/tts-refs/ref_a.wav https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/asset/zero_shot_prompt.wav
curl -L -o static/tts-refs/ref_b.wav https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/asset/cross_lingual_prompt.wav
python3 -c "import wave; [print(f, wave.open('static/tts-refs/'+f).getparams()) for f in ('ref_a.wav','ref_b.wav')]"
```

Expected: 두 파일 모두 wave params 출력 (WAV 형식 확인). 실패 시 URL의 브랜치를 `master`로 바꿔 재시도.

- [ ] **Step 2: 실패하는 테스트 작성**

`test/test_tts_config.py`:

```python
"""test_tts_config.py — 엔진 레지스트리 무결성 검증"""
import os

from config.tts_config import TTS_ENGINES, TTS_REFS_DIR

REQUIRED_KEYS = {'name', 'description', 'image', 'container', 'port',
                 'adapter', 'languages', 'vram', 'docker_args', 'command', 'voices'}


def test_engines_have_required_keys():
    assert set(TTS_ENGINES) == {'kokoro', 'cosyvoice'}
    for spec in TTS_ENGINES.values():
        assert REQUIRED_KEYS <= set(spec)
        assert spec['voices'], '보이스가 최소 1개 필요'


def test_container_names_and_ports_unique():
    containers = [s['container'] for s in TTS_ENGINES.values()]
    ports = [s['port'] for s in TTS_ENGINES.values()]
    assert len(set(containers)) == len(containers)
    assert len(set(ports)) == len(ports)


def test_cosyvoice_ref_files_exist():
    for voice in TTS_ENGINES['cosyvoice']['voices']:
        assert os.path.isfile(os.path.join(TTS_REFS_DIR, voice['file']))


def test_cosyvoice_has_sample_rate():
    # 서버가 헤더 없는 raw PCM을 반환하므로 WAV 래핑에 필수
    assert TTS_ENGINES['cosyvoice']['sample_rate'] == 24000
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.tts_config'`

- [ ] **Step 4: 레지스트리 구현**

`config/tts_config.py`:

```python
"""
TTS 엔진 레지스트리 — 지원 엔진 카탈로그
새 엔진 추가 = 여기에 항목 1개 + service/tts/adapters.py에 어댑터 1개
"""
import os

# 제로샷 레퍼런스 음성 저장 위치 (CosyVoice 레포 Apache-2.0 샘플)
TTS_REFS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'static', 'tts-refs'))

TTS_ENGINES = {
    'kokoro': {
        'name': 'Kokoro-82M',
        'description': '초경량 영어 TTS — OpenAI 호환 API, VRAM 부담 거의 없음',
        'image': 'ghcr.io/remsky/kokoro-fastapi-gpu:latest',
        'container': 'suh-tts-kokoro',
        'port': 8880,
        'adapter': 'kokoro',
        'languages': ['en'],
        'vram': '~1GB',
        'docker_args': ['--gpus', 'all'],
        'command': [],  # 이미지 기본 CMD 사용
        'voices': [
            {'id': 'af_heart', 'name': '여성 (미국)'},
            {'id': 'am_michael', 'name': '남성 (미국)'},
            {'id': 'bf_emma', 'name': '여성 (영국)'},
        ],
    },
    'cosyvoice': {
        'name': 'CosyVoice2-0.5B',
        'description': '한국어 포함 다국어 TTS — 제로샷 보이스 클로닝 (cross-lingual)',
        'image': 'cassiiopeia/suh-tts-cosyvoice:latest',
        'container': 'suh-tts-cosyvoice',
        'port': 50000,
        'adapter': 'cosyvoice',
        'languages': ['ko', 'en', 'zh', 'ja'],
        'vram': '~5GB',
        # 서버가 헤더 없는 int16 mono PCM을 반환 → 어댑터가 WAV로 감쌀 때 사용.
        # CosyVoice2의 출력 샘플레이트 24kHz — 스모크 테스트에서 음높이 이상 시 재확인
        'sample_rate': 24000,
        'docker_args': ['--gpus', 'all', '-v', 'suh-tts-models:/root/.cache'],
        'command': [],  # docker/cosyvoice/Dockerfile의 CMD가 fastapi 서버 기동
        'voices': [
            {'id': 'ref_a', 'name': '기본 보이스 A (중국어 화자)', 'file': 'ref_a.wav'},
            {'id': 'ref_b', 'name': '기본 보이스 B (영어 화자)', 'file': 'ref_b.wav'},
        ],
    },
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_config.py -v`
Expected: 4 passed

- [ ] **Step 6: 커밋**

```bash
git add suh-ai-server/flask/config/tts_config.py suh-ai-server/flask/static/tts-refs suh-ai-server/flask/test/test_tts_config.py
git commit -m "TTS 엔진 매니저 : feat : 엔진 레지스트리 및 레퍼런스 음성 자산 추가"
```

---

### Task 2: TTS 어댑터 (Kokoro / CosyVoice)

**Files:**
- Create: `suh-ai-server/flask/service/tts/__init__.py` (빈 파일)
- Create: `suh-ai-server/flask/service/tts/adapters.py`
- Test: `suh-ai-server/flask/test/test_tts_adapters.py`

**Interfaces:**
- Consumes: `config.tts_config.TTS_ENGINES`, `TTS_REFS_DIR` (Task 1)
- Produces: `get_adapter(engine_id: str) -> TtsAdapter` — `TtsAdapter.synthesize(text: str, voice: str, speed: float) -> bytes(WAV)`, `.health() -> bool`, `.voices() -> list`

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_tts_adapters.py`:

```python
"""test_tts_adapters.py — 어댑터 요청/응답 변환 검증 (HTTP는 mock)"""
import io
import wave

import pytest

import service.tts.adapters as adapters
from service.tts.adapters import get_adapter


class FakeResponse:
    def __init__(self, content=b'', status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f'HTTP {self.status_code}')


def test_kokoro_synthesize_posts_openai_format(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['json'] = kwargs['json']
        return FakeResponse(b'RIFF....WAVE')

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    wav = get_adapter('kokoro').synthesize('hello', 'af_heart', 1.2)
    assert wav == b'RIFF....WAVE'
    assert captured['url'] == 'http://127.0.0.1:8880/v1/audio/speech'
    assert captured['json'] == {'model': 'kokoro', 'voice': 'af_heart',
                                'input': 'hello', 'response_format': 'wav', 'speed': 1.2}


def test_cosyvoice_synthesize_wraps_pcm_as_wav(monkeypatch):
    pcm = b'\x00\x01' * 2400  # int16 mono 샘플 2400개
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['data'] = kwargs['data']
        captured['has_file'] = 'prompt_wav' in kwargs['files']
        return FakeResponse(pcm)

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    wav_bytes = get_adapter('cosyvoice').synthesize('안녕하세요', 'ref_a', 1.0)
    assert captured['url'] == 'http://127.0.0.1:50000/inference_cross_lingual'
    assert captured['data'] == {'tts_text': '안녕하세요'}
    assert captured['has_file'] is True
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 2400


def test_cosyvoice_unknown_voice_falls_back_to_first(monkeypatch):
    monkeypatch.setattr(adapters.requests, 'post', lambda url, **kw: FakeResponse(b'\x00\x00'))
    # 존재하지 않는 voice id — 예외 없이 첫 보이스로 동작해야 한다
    get_adapter('cosyvoice').synthesize('테스트', 'no-such-voice', 1.0)


def test_health_false_when_connection_fails(monkeypatch):
    def boom(url, timeout):
        raise adapters.requests.RequestException('refused')

    monkeypatch.setattr(adapters.requests, 'get', boom)
    assert get_adapter('kokoro').health() is False
    assert get_adapter('cosyvoice').health() is False


def test_get_adapter_unknown_engine_raises():
    with pytest.raises(KeyError):
        get_adapter('no-such-engine')
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_adapters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'service.tts'`

- [ ] **Step 3: 어댑터 구현**

`service/tts/__init__.py`: 빈 파일 생성.

`service/tts/adapters.py`:

```python
"""
TTS 엔진 어댑터 — 엔진별 API 형식 차이를 공통 인터페이스로 흡수
공통 인터페이스: synthesize(text, voice, speed) -> WAV bytes / health() / voices()
"""
import io
import os
import wave

import requests

from config.tts_config import TTS_ENGINES, TTS_REFS_DIR

# 합성 대기 한도 — 컨테이너 첫 요청은 모델 워밍업으로 오래 걸릴 수 있다
SYNTH_TIMEOUT = 120
HEALTH_TIMEOUT = 3


class TtsAdapter:
    def __init__(self, engine_id: str):
        self.engine = TTS_ENGINES[engine_id]
        self.base_url = f"http://127.0.0.1:{self.engine['port']}"

    def synthesize(self, text: str, voice: str, speed: float) -> bytes:
        raise NotImplementedError

    def health(self) -> bool:
        raise NotImplementedError

    def voices(self) -> list:
        return self.engine['voices']


class KokoroAdapter(TtsAdapter):
    """Kokoro-FastAPI — OpenAI 호환 /v1/audio/speech, WAV 직접 반환"""

    def synthesize(self, text, voice, speed):
        resp = requests.post(
            f'{self.base_url}/v1/audio/speech',
            json={'model': 'kokoro', 'voice': voice, 'input': text,
                  'response_format': 'wav', 'speed': speed},
            timeout=SYNTH_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content

    def health(self):
        try:
            return requests.get(f'{self.base_url}/v1/audio/voices',
                                timeout=HEALTH_TIMEOUT).status_code == 200
        except requests.RequestException:
            return False


class CosyVoiceAdapter(TtsAdapter):
    """CosyVoice fastapi 서버 — cross_lingual 모드로 레퍼런스 화자가 다른 언어를 말하게 한다.
    speed 파라미터는 서버가 미지원이라 무시한다."""

    def synthesize(self, text, voice, speed):
        ref = next((v for v in self.engine['voices'] if v['id'] == voice),
                   self.engine['voices'][0])
        ref_path = os.path.join(TTS_REFS_DIR, ref['file'])
        with open(ref_path, 'rb') as f:
            resp = requests.post(
                f'{self.base_url}/inference_cross_lingual',
                data={'tts_text': text},
                files={'prompt_wav': f},
                timeout=SYNTH_TIMEOUT,
            )
        resp.raise_for_status()
        return self._pcm_to_wav(resp.content, self.engine['sample_rate'])

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        """서버 응답은 헤더 없는 int16 mono PCM — 브라우저 재생을 위해 WAV로 감싼다"""
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm)
        return buf.getvalue()

    def health(self):
        try:
            # 전용 헬스 엔드포인트가 없어 FastAPI 자동 문서(/docs)로 대신 확인
            return requests.get(f'{self.base_url}/docs',
                                timeout=HEALTH_TIMEOUT).status_code == 200
        except requests.RequestException:
            return False


_ADAPTER_CLASSES = {'kokoro': KokoroAdapter, 'cosyvoice': CosyVoiceAdapter}


def get_adapter(engine_id: str) -> TtsAdapter:
    return _ADAPTER_CLASSES[TTS_ENGINES[engine_id]['adapter']](engine_id)
```

주의: `test_cosyvoice_unknown_voice_falls_back_to_first`에서 `sample_rate` 접근이 일어나므로 fake 응답에도 `_pcm_to_wav`가 실행된다 — 정상.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_adapters.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/tts suh-ai-server/flask/test/test_tts_adapters.py
git commit -m "TTS 엔진 매니저 : feat : Kokoro·CosyVoice 어댑터 추가"
```

---

### Task 3: 엔진 수명주기 서비스 (docker CLI)

**Files:**
- Create: `suh-ai-server/flask/service/tts_service.py`
- Test: `suh-ai-server/flask/test/test_tts_service.py`

**Interfaces:**
- Consumes: `TTS_ENGINES` (Task 1), `get_adapter` (Task 2)
- Produces: `TtsService` — `get_engines_state() -> list[dict]` (dict 키: `id, name, description, languages, vram, voices, status, install_error`; status ∈ `not_installed|installing|stopped|starting|running|error`), `install(engine_id)`, `start(engine_id)`, `stop(engine_id)`, `logs(engine_id) -> str`, `get_running_engine() -> str|None`

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_tts_service.py`:

```python
"""test_tts_service.py — 엔진 수명주기 상태 전이 검증 (docker CLI·어댑터 mock)"""
import subprocess
from types import SimpleNamespace

import pytest

import service.tts_service as tts_service_module
from service.tts_service import TtsService


class FakeDocker:
    """docker CLI 흉내 — images/running 집합으로 상태를 제어하고 호출을 기록한다"""

    def __init__(self, images=(), running=()):
        self.images = set(images)
        self.running = set(running)
        self.calls = []

    def run(self, cmd, **kwargs):
        args = cmd[1:]  # 'docker' 제거
        self.calls.append(args)
        ok = SimpleNamespace(returncode=0, stdout='', stderr='')
        if args[:2] == ['image', 'inspect']:
            if args[2] in self.images:
                return ok
            return SimpleNamespace(returncode=1, stdout='', stderr='No such image')
        if args[0] == 'ps':
            name_filter = args[args.index('--filter') + 1]  # 'name=^X$'
            name = name_filter[len('name=^'):-1]
            return SimpleNamespace(returncode=0,
                                   stdout=name + '\n' if name in self.running else '',
                                   stderr='')
        if args[0] == 'run':
            self.running.add(args[args.index('--name') + 1])
            return ok
        if args[0] == 'stop':
            self.running.discard(args[1])
            return ok
        return ok


@pytest.fixture
def fake(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setattr(tts_service_module.subprocess, 'run', fake.run)
    return fake


def test_state_not_installed(fake):
    states = TtsService().get_engines_state()
    assert {s['id']: s['status'] for s in states} == {
        'kokoro': 'not_installed', 'cosyvoice': 'not_installed'}


def test_state_running_needs_health(fake, monkeypatch):
    fake.images = {'ghcr.io/remsky/kokoro-fastapi-gpu:latest'}
    fake.running = {'suh-tts-kokoro'}
    monkeypatch.setattr(tts_service_module, 'get_adapter',
                        lambda eid: SimpleNamespace(health=lambda: False))
    states = {s['id']: s['status'] for s in TtsService().get_engines_state()}
    assert states['kokoro'] == 'starting'  # 컨테이너는 떠 있지만 모델 로딩 중


def test_start_requires_image(fake):
    with pytest.raises(ValueError):
        TtsService().start('kokoro')


def test_start_stops_other_engine_first(fake):
    fake.images = {'ghcr.io/remsky/kokoro-fastapi-gpu:latest',
                   'cassiiopeia/suh-tts-cosyvoice:latest'}
    fake.running = {'suh-tts-cosyvoice'}
    TtsService().start('kokoro')
    assert 'suh-tts-cosyvoice' not in fake.running  # 1개만 실행 정책
    assert 'suh-tts-kokoro' in fake.running


def test_start_publishes_port_and_restart_policy(fake):
    fake.images = {'ghcr.io/remsky/kokoro-fastapi-gpu:latest'}
    TtsService().start('kokoro')
    run_call = next(c for c in fake.calls if c[0] == 'run')
    assert '-p' in run_call and '8880:8880' in run_call
    assert '--restart' in run_call and 'unless-stopped' in run_call


def test_get_running_engine(fake):
    fake.running = {'suh-tts-kokoro'}
    assert TtsService().get_running_engine() == 'kokoro'
    fake.running = set()
    assert TtsService().get_running_engine() is None


def test_install_duplicate_rejected(fake, monkeypatch):
    svc = TtsService()
    # 워커 스레드가 실제로 돌지 않게 pull을 무력화
    monkeypatch.setattr(svc, '_pull', lambda *a: None)
    svc._installs['kokoro'] = {'status': 'pulling', 'error': None}
    with pytest.raises(ValueError):
        svc.install('kokoro')
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'service.tts_service'`

- [ ] **Step 3: 서비스 구현**

`service/tts_service.py`:

```python
"""
TTS 엔진 수명주기 관리 — docker CLI subprocess 제어
(palworld_service가 NSSM을 subprocess로 제어하는 것과 같은 패턴)
정책: VRAM 8GB 보호를 위해 한 번에 1개 엔진만 실행
"""
import logging
import subprocess
import threading

from config.tts_config import TTS_ENGINES
from service.tts.adapters import get_adapter

logger = logging.getLogger(__name__)

DOCKER_TIMEOUT = 60
PULL_TIMEOUT = 3600  # 이미지가 수 GB — 서버 회선 기준 여유값


class TtsService:

    def __init__(self):
        self._install_lock = threading.Lock()
        self._installs = {}  # engine_id -> {'status': 'pulling'|'done'|'error', 'error': str|None}

    # ---------- docker CLI 래퍼 ----------

    def _run_docker(self, args, timeout=DOCKER_TIMEOUT, check=True):
        result = subprocess.run(['docker'] + args, capture_output=True,
                                text=True, timeout=timeout)
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"docker {' '.join(args)} failed")
        return result.stdout

    def _image_exists(self, image: str) -> bool:
        try:
            self._run_docker(['image', 'inspect', image])
            return True
        except RuntimeError:
            return False

    def _container_running(self, container: str) -> bool:
        out = self._run_docker(['ps', '--filter', f'name=^{container}$',
                                '--format', '{{.Names}}'])
        return container in out.split()

    # ---------- 조회 ----------

    def get_engines_state(self) -> list:
        """카탈로그 + 엔진별 상태 (관리자 화면 폴링·외부 조회용)"""
        states = []
        for engine_id, spec in TTS_ENGINES.items():
            install = self._installs.get(engine_id, {})
            try:
                if install.get('status') == 'pulling':
                    status = 'installing'
                elif self._container_running(spec['container']):
                    # 컨테이너는 떠 있어도 첫 기동은 모델 다운로드/로딩 중일 수 있다
                    status = 'running' if get_adapter(engine_id).health() else 'starting'
                elif self._image_exists(spec['image']):
                    status = 'stopped'
                else:
                    status = 'not_installed'
            except Exception as e:  # docker 데몬 다운 등 — 원인 그대로 노출 (palworld 패턴)
                logger.error(f"TTS state check failed ({engine_id}): {str(e)}")
                status = 'error'
            states.append({
                'id': engine_id,
                'name': spec['name'],
                'description': spec['description'],
                'languages': spec['languages'],
                'vram': spec['vram'],
                'voices': [{'id': v['id'], 'name': v['name']} for v in spec['voices']],
                'status': status,
                'install_error': install.get('error'),
            })
        return states

    def get_running_engine(self):
        """실행 중 엔진 id (없으면 None) — /tts에서 engine 생략 시 사용"""
        for engine_id, spec in TTS_ENGINES.items():
            try:
                if self._container_running(spec['container']):
                    return engine_id
            except Exception:
                continue
        return None

    # ---------- 제어 ----------

    def install(self, engine_id: str):
        """이미지 pull을 백그라운드 스레드로 시작 (download_queue_service 패턴)"""
        spec = TTS_ENGINES[engine_id]
        with self._install_lock:
            if self._installs.get(engine_id, {}).get('status') == 'pulling':
                raise ValueError('이미 설치 진행 중입니다')
            self._installs[engine_id] = {'status': 'pulling', 'error': None}
        threading.Thread(target=self._pull, args=(engine_id, spec['image']),
                         daemon=True, name=f'tts-pull-{engine_id}').start()

    def _pull(self, engine_id: str, image: str):
        try:
            self._run_docker(['pull', image], timeout=PULL_TIMEOUT)
            state = {'status': 'done', 'error': None}
            logger.info(f"TTS image pull done: {image}")
        except Exception as e:
            state = {'status': 'error', 'error': str(e)}
            logger.error(f"TTS image pull failed ({engine_id}): {str(e)}")
        with self._install_lock:
            self._installs[engine_id] = state

    def start(self, engine_id: str):
        spec = TTS_ENGINES[engine_id]
        if not self._image_exists(spec['image']):
            raise ValueError('이미지가 설치되지 않았습니다 — 먼저 설치를 실행하세요')
        # 1개만 실행 정책 — 다른 실행 중 엔진을 먼저 내린다
        for other_id, other in TTS_ENGINES.items():
            if other_id != engine_id and self._container_running(other['container']):
                self._run_docker(['stop', other['container']], timeout=120)
                logger.info(f"TTS engine stopped for switch: {other_id}")
        # 이전 컨테이너 잔재 제거 (없으면 무시) 후 새로 기동
        self._run_docker(['rm', '-f', spec['container']], check=False)
        args = (['run', '-d', '--name', spec['container'],
                 '--restart', 'unless-stopped',
                 '-p', f"{spec['port']}:{spec['port']}"]
                + spec['docker_args'] + [spec['image']] + spec['command'])
        self._run_docker(args, timeout=300)
        logger.info(f"TTS engine started: {engine_id}")

    def stop(self, engine_id: str):
        self._run_docker(['stop', TTS_ENGINES[engine_id]['container']], timeout=120)
        logger.info(f"TTS engine stopped: {engine_id}")

    def logs(self, engine_id: str) -> str:
        """컨테이너 로그 tail — 설치/기동 진행 상황 표시용 (stderr 포함)"""
        result = subprocess.run(
            ['docker', 'logs', '--tail', '80', TTS_ENGINES[engine_id]['container']],
            capture_output=True, text=True, timeout=DOCKER_TIMEOUT,
            stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or 'docker logs failed')
        return result.stdout
```

주의: `capture_output=True`와 `stderr=subprocess.STDOUT`는 함께 쓸 수 없다 — `logs()`는 `stdout=subprocess.PIPE, stderr=subprocess.STDOUT`로 작성한다:

```python
    def logs(self, engine_id: str) -> str:
        """컨테이너 로그 tail — 설치/기동 진행 상황 표시용 (stderr 포함)"""
        result = subprocess.run(
            ['docker', 'logs', '--tail', '80', TTS_ENGINES[engine_id]['container']],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=DOCKER_TIMEOUT)
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or 'docker logs failed')
        return result.stdout
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_service.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/tts_service.py suh-ai-server/flask/test/test_tts_service.py
git commit -m "TTS 엔진 매니저 : feat : docker CLI 기반 엔진 수명주기 서비스 추가"
```

---

### Task 4: TTS 라우터 + 감사로그 + 앱 등록

**Files:**
- Create: `suh-ai-server/flask/router/tts_router.py`
- Modify: `suh-ai-server/flask/service/audit_service.py` (enum 추가)
- Modify: `suh-ai-server/flask/app.py` (blueprint 등록)
- Test: `suh-ai-server/flask/test/test_tts_router.py`

**Interfaces:**
- Consumes: `TtsService` (Task 3), `get_adapter` (Task 2), `audit_service.record` (기존)
- Produces: HTTP API — `GET /tts/engines`, `POST /tts/engines/<id>/install|start|stop`, `GET /tts/engines/<id>/logs`, `POST /tts` (json `{text, engine?, voice?, speed?}` → `audio/wav`)

- [ ] **Step 1: 감사로그 enum 추가**

`service/audit_service.py`의 `AuditCategory`에 `TTS = "TTS"`, `AuditAction`에 3개 추가:

```python
class AuditCategory(str, Enum):
    PALWORLD = "PALWORLD"
    TTS = "TTS"
    SYSTEM = "SYSTEM"  # 향후 확장용


class AuditAction(str, Enum):
    SERVER_START = "SERVER_START"
    SERVER_STOP = "SERVER_STOP"
    SERVER_RESTART = "SERVER_RESTART"
    SETTINGS_UPDATE = "SETTINGS_UPDATE"
    BACKUP_CREATE = "BACKUP_CREATE"
    SERVER_UPDATE = "SERVER_UPDATE"
    TTS_INSTALL = "TTS_INSTALL"
    TTS_START = "TTS_START"
    TTS_STOP = "TTS_STOP"
```

(category/action은 DB VARCHAR라 마이그레이션 불필요 — audit_service 모듈 주석 참고)

- [ ] **Step 2: 실패하는 테스트 작성**

`test/test_tts_router.py`:

```python
"""test_tts_router.py — /tts/* 엔드포인트 검증 (서비스·어댑터·감사로그 mock)"""
import pytest
from flask import Flask

import router.tts_router as tts_router_module
from router.tts_router import tts_bp


@pytest.fixture
def client(monkeypatch):
    # DB 접근 차단 — 감사로그는 no-op
    monkeypatch.setattr(tts_router_module.audit_service, 'record',
                        lambda *a, **kw: True)
    app = Flask(__name__)
    app.register_blueprint(tts_bp)
    return app.test_client()


def test_engines_state(client, monkeypatch):
    monkeypatch.setattr(tts_router_module.tts_service, 'get_engines_state',
                        lambda: [{'id': 'kokoro', 'status': 'stopped'}])
    resp = client.get('/tts/engines')
    assert resp.status_code == 200
    assert resp.get_json()['engines'][0]['id'] == 'kokoro'


def test_control_unknown_engine_404(client):
    assert client.post('/tts/engines/nope/start').status_code == 404


def test_control_unknown_action_404(client):
    assert client.post('/tts/engines/kokoro/explode').status_code == 404


def test_control_start_records_audit(client, monkeypatch):
    calls = []
    monkeypatch.setattr(tts_router_module.audit_service, 'record',
                        lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(tts_router_module.tts_service, 'start', lambda eid: None)
    monkeypatch.setattr(tts_router_module.tts_service, 'get_engines_state', lambda: [])
    resp = client.post('/tts/engines/kokoro/start')
    assert resp.status_code == 200
    assert len(calls) == 1


def test_control_conflict_returns_409(client, monkeypatch):
    def dup(eid):
        raise ValueError('이미 설치 진행 중입니다')

    monkeypatch.setattr(tts_router_module.tts_service, 'install', dup)
    assert client.post('/tts/engines/kokoro/install').status_code == 409


def test_synthesize_requires_text(client):
    assert client.post('/tts', json={}).status_code == 400


def test_synthesize_no_running_engine_503(client, monkeypatch):
    monkeypatch.setattr(tts_router_module.tts_service, 'get_running_engine',
                        lambda: None)
    resp = client.post('/tts', json={'text': '안녕'})
    assert resp.status_code == 503


def test_synthesize_returns_wav(client, monkeypatch):
    class FakeAdapter:
        def synthesize(self, text, voice, speed):
            return b'RIFF-fake-wav'

    monkeypatch.setattr(tts_router_module.tts_service, 'get_running_engine',
                        lambda: 'kokoro')
    monkeypatch.setattr(tts_router_module, 'get_adapter', lambda eid: FakeAdapter())
    resp = client.post('/tts', json={'text': 'hello'})
    assert resp.status_code == 200
    assert resp.mimetype == 'audio/wav'
    assert resp.data == b'RIFF-fake-wav'


def test_synthesize_engine_down_503(client, monkeypatch):
    class DeadAdapter:
        def synthesize(self, text, voice, speed):
            raise Exception('connection refused')

    monkeypatch.setattr(tts_router_module, 'get_adapter', lambda eid: DeadAdapter())
    resp = client.post('/tts', json={'text': 'hello', 'engine': 'kokoro'})
    assert resp.status_code == 503
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'router.tts_router'`

- [ ] **Step 4: 라우터 구현**

`router/tts_router.py`:

```python
"""
TTS router — 음성 합성 API + 엔진 수명주기 제어
관리 페이지(/admin/tts)가 사용하고, /tts는 외부 클라이언트에도 공개된다
"""
import logging

from flask import Blueprint, Response, jsonify, request

from config.tts_config import TTS_ENGINES
from service import audit_service
from service.audit_service import AuditCategory, AuditAction
from service.tts.adapters import get_adapter
from service.tts_service import TtsService

logger = logging.getLogger(__name__)

tts_bp = Blueprint('tts', __name__)
tts_service = TtsService()

_CONTROL_AUDIT_ACTIONS = {
    'install': AuditAction.TTS_INSTALL,
    'start': AuditAction.TTS_START,
    'stop': AuditAction.TTS_STOP,
}


def _client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '')


@tts_bp.route('/tts/engines', methods=['GET'])
def engines_state():
    """엔진 카탈로그 + 상태 (관리 페이지 폴링용)"""
    return jsonify({'success': True, 'engines': tts_service.get_engines_state()}), 200


@tts_bp.route('/tts/engines/<engine_id>/<action>', methods=['POST'])
def engine_control(engine_id, action):
    """엔진 설치/시작/중지 — 관리 행위라 감사로그 기록"""
    if engine_id not in TTS_ENGINES:
        return jsonify({'error': f'알 수 없는 엔진: {engine_id}'}), 404
    if action not in _CONTROL_AUDIT_ACTIONS:
        return jsonify({'error': f'알 수 없는 동작: {action}'}), 404
    try:
        getattr(tts_service, action)(engine_id)
    except ValueError as e:  # 미설치 상태 start, 중복 install 등
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        logger.error(f"TTS engine {action} failed ({engine_id}): {str(e)}")
        return jsonify({'error': str(e)}), 500
    audit_service.record(AuditCategory.TTS, _CONTROL_AUDIT_ACTIONS[action],
                         _client_ip(), {'engine': engine_id})
    return jsonify({'success': True, 'engines': tts_service.get_engines_state()}), 200


@tts_bp.route('/tts/engines/<engine_id>/logs', methods=['GET'])
def engine_logs(engine_id):
    """컨테이너 로그 tail — 설치·모델 다운로드 진행 확인용"""
    if engine_id not in TTS_ENGINES:
        return jsonify({'error': f'알 수 없는 엔진: {engine_id}'}), 404
    try:
        return jsonify({'success': True, 'logs': tts_service.logs(engine_id)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@tts_bp.route('/tts', methods=['POST'])
def synthesize():
    """텍스트 → WAV. engine 생략 시 실행 중 엔진 사용"""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'text is required'}), 400
    engine_id = data.get('engine') or tts_service.get_running_engine()
    if not engine_id:
        return jsonify({'error': '실행 중인 TTS 엔진이 없습니다'}), 503
    if engine_id not in TTS_ENGINES:
        return jsonify({'error': f'알 수 없는 엔진: {engine_id}'}), 404
    voice = data.get('voice') or TTS_ENGINES[engine_id]['voices'][0]['id']
    try:
        speed = float(data.get('speed', 1.0))
    except (TypeError, ValueError):
        return jsonify({'error': 'speed must be a number'}), 400
    try:
        wav = get_adapter(engine_id).synthesize(text, voice, speed)
    except Exception as e:
        logger.error(f"TTS synth failed ({engine_id}): {str(e)}")
        return jsonify({'error': f'합성 실패: {str(e)}'}), 503
    return Response(wav, mimetype='audio/wav')
```

- [ ] **Step 5: app.py에 blueprint 등록**

`app.py` import 블록에 추가:

```python
from router.tts_router import tts_bp
```

`app.register_blueprint(ollama_bp)` 아래에 추가:

```python
app.register_blueprint(tts_bp)
```

- [ ] **Step 6: 테스트 통과 확인 (전체 회귀 포함)**

Run: `cd suh-ai-server/flask && python3 -m pytest test/ -v`
Expected: 신규 9개 포함 전체 passed (기존 테스트 깨짐 없음)

- [ ] **Step 7: 커밋**

```bash
git add suh-ai-server/flask/router/tts_router.py suh-ai-server/flask/service/audit_service.py suh-ai-server/flask/app.py suh-ai-server/flask/test/test_tts_router.py
git commit -m "TTS 엔진 매니저 : feat : /tts 합성·엔진 제어 API 및 감사로그 추가"
```

---

### Task 5: Swagger 문서

**Files:**
- Create: `suh-ai-server/flask/router/tts_swagger.py`
- Modify: `suh-ai-server/flask/router/swagger_router.py`
- Test: `suh-ai-server/flask/test/test_tts_router.py` (테스트 추가)

**Interfaces:**
- Consumes: `swagger_router.py`의 기존 `swagger_spec["paths"].update(PALWORLD_SWAGGER_PATHS)` 병합 지점 (약 400행)
- Produces: `TTS_SWAGGER_PATHS: dict` — swagger.json에 `/tts`, `/tts/engines` 경로 노출

- [ ] **Step 1: 실패하는 테스트 추가**

`test/test_tts_router.py` 하단에 추가:

```python
def test_swagger_includes_tts_paths():
    from router.tts_swagger import TTS_SWAGGER_PATHS
    assert '/tts' in TTS_SWAGGER_PATHS
    assert '/tts/engines' in TTS_SWAGGER_PATHS
    assert '/tts/engines/{engine_id}/{action}' in TTS_SWAGGER_PATHS
```

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_router.py::test_swagger_includes_tts_paths -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 2: Swagger 경로 정의**

`router/tts_swagger.py` (palworld_swagger.py 패턴):

```python
"""
TTS API Swagger 경로 정의 — swagger_router가 병합해 노출
"""

TTS_SWAGGER_PATHS = {
    "/tts": {
        "post": {
            "tags": ["TTS"],
            "summary": "텍스트 음성 합성 (WAV)",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "example": "안녕하세요"},
                        "engine": {"type": "string", "example": "cosyvoice",
                                   "description": "생략 시 실행 중 엔진 사용"},
                        "voice": {"type": "string", "example": "ref_a"},
                        "speed": {"type": "number", "example": 1.0,
                                  "description": "엔진이 미지원이면 무시"},
                    },
                }}},
            },
            "responses": {
                "200": {"description": "WAV 오디오",
                        "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}},
                "400": {"description": "text 누락 또는 speed 형식 오류"},
                "503": {"description": "실행 중 엔진 없음 또는 엔진 미응답"},
            },
        }
    },
    "/tts/engines": {
        "get": {
            "tags": ["TTS"],
            "summary": "TTS 엔진 카탈로그·상태 조회",
            "responses": {"200": {"description": "엔진 목록 (status: not_installed|installing|stopped|starting|running|error)"}},
        }
    },
    "/tts/engines/{engine_id}/{action}": {
        "post": {
            "tags": ["TTS"],
            "summary": "엔진 제어 (install / start / stop)",
            "parameters": [
                {"name": "engine_id", "in": "path", "required": True,
                 "schema": {"type": "string", "enum": ["kokoro", "cosyvoice"]}},
                {"name": "action", "in": "path", "required": True,
                 "schema": {"type": "string", "enum": ["install", "start", "stop"]}},
            ],
            "responses": {
                "200": {"description": "제어 성공 + 최신 엔진 상태"},
                "404": {"description": "알 수 없는 엔진/동작"},
                "409": {"description": "중복 설치 또는 미설치 상태 start"},
            },
        }
    },
    "/tts/engines/{engine_id}/logs": {
        "get": {
            "tags": ["TTS"],
            "summary": "엔진 컨테이너 로그 tail",
            "parameters": [
                {"name": "engine_id", "in": "path", "required": True,
                 "schema": {"type": "string"}},
            ],
            "responses": {"200": {"description": "로그 텍스트"}},
        }
    },
}
```

- [ ] **Step 3: swagger_router.py에 병합**

import 추가:

```python
from router.tts_swagger import TTS_SWAGGER_PATHS
```

기존 `swagger_spec["paths"].update(PALWORLD_SWAGGER_PATHS)` (약 400행) 바로 아래에 추가:

```python
    swagger_spec["paths"].update(TTS_SWAGGER_PATHS)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_router.py -v`
Expected: 10 passed

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/router/tts_swagger.py suh-ai-server/flask/router/swagger_router.py suh-ai-server/flask/test/test_tts_router.py
git commit -m "TTS 엔진 매니저 : docs : Swagger에 TTS API 경로 추가"
```

---

### Task 6: 관리자 페이지 (/admin/tts)

**Files:**
- Modify: `suh-ai-server/flask/router/admin_router.py` (라우트 추가)
- Modify: `suh-ai-server/flask/templates/admin/base.html:77-81` (사이드바 메뉴)
- Create: `suh-ai-server/flask/templates/admin/tts.html`
- Create: `suh-ai-server/flask/static/js/tts.js`
- Test: `suh-ai-server/flask/test/test_admin_router.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 4의 HTTP API (`../tts/engines`, `../tts`, `../tts/engines/<id>/<action>`, `../tts/engines/<id>/logs`), 전역 JS 헬퍼 `apiFetch`/`escapeHtml`/`showToast` (admin-common.js), 템플릿 헬퍼 `asset()` (admin_router)
- Produces: `GET /admin/tts` 페이지

- [ ] **Step 1: 실패하는 테스트 추가**

`test/test_admin_router.py`의 기존 페이지 테스트 옆에 추가 (파일의 기존 fixture/스타일 확인 후 동일하게):

```python
def test_tts_page_renders(client):
    resp = client.get('/admin/tts')
    assert resp.status_code == 200
    assert 'TTS'.encode() in resp.data
```

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_admin_router.py -v`
Expected: 신규 테스트 FAIL (404)

- [ ] **Step 2: admin_router에 라우트 추가**

`router/admin_router.py` 하단에:

```python
@admin_bp.route('/admin/tts', methods=['GET'])
def tts():
    """TTS 엔진 관리 페이지 (설치·전환·테스트)"""
    return render_template('admin/tts.html', root='..', active='tts')
```

- [ ] **Step 3: base.html 사이드바에 메뉴 추가**

`templates/admin/base.html`의 "모델 관리" `<li>` (77-81행) 바로 아래에:

```html
        <li>
          <a href="{{ root }}/admin/tts" class="{{ 'menu-active' if active == 'tts' else '' }}">
            <i data-lucide="audio-lines" class="size-5"></i>TTS 관리
          </a>
        </li>
```

- [ ] **Step 4: 페이지 템플릿 작성**

`templates/admin/tts.html`:

```html
{% extends "admin/base.html" %}
{% block title %}TTS 관리 | SUH AI Server{% endblock %}
{% block page_title %}TTS 관리{% endblock %}
{% block content %}
<div class="space-y-6 max-w-6xl mx-auto">

  <!-- 엔진 카탈로그 -->
  <div class="card bg-base-100 shadow">
    <div class="card-body">
      <div class="flex items-center justify-between">
        <h2 class="card-title text-base">
          <i data-lucide="audio-lines" class="size-5 text-primary"></i>TTS 엔진
        </h2>
        <span class="text-xs opacity-60">VRAM 보호를 위해 한 번에 1개만 실행됩니다</span>
      </div>
      <div id="engines-error" class="alert alert-error hidden"><span></span></div>
      <div id="engine-cards" class="grid md:grid-cols-2 gap-4">
        <div class="text-center opacity-60 py-8">불러오는 중...</div>
      </div>
    </div>
  </div>

  <!-- 합성 테스트 -->
  <div class="card bg-base-100 shadow">
    <div class="card-body space-y-3">
      <h2 class="card-title text-base">
        <i data-lucide="mic" class="size-5 text-primary"></i>합성 테스트
        <span id="test-engine-badge" class="badge badge-ghost badge-sm">실행 중 엔진 없음</span>
      </h2>
      <textarea id="tts-text" class="textarea textarea-bordered w-full" rows="3"
                placeholder="합성할 텍스트를 입력하세요"></textarea>
      <div class="flex flex-wrap items-end gap-4">
        <label class="form-control">
          <span class="label-text text-xs mb-1">보이스</span>
          <select id="tts-voice" class="select select-bordered select-sm min-w-48"></select>
        </label>
        <label class="form-control">
          <span class="label-text text-xs mb-1">속도: <span id="speed-value">1.0</span>x</span>
          <input id="tts-speed" type="range" min="0.5" max="2" step="0.1" value="1"
                 class="range range-sm w-40" />
        </label>
        <button id="tts-run" class="btn btn-primary btn-sm">
          <i data-lucide="play" class="size-4"></i>합성
        </button>
      </div>
      <div id="tts-result" class="hidden items-center gap-3 flex">
        <audio id="tts-audio" controls class="w-full max-w-md"></audio>
        <a id="tts-download" class="btn btn-ghost btn-sm" download="tts.wav">
          <i data-lucide="download" class="size-4"></i>WAV
        </a>
      </div>
    </div>
  </div>

</div>

<!-- 로그 모달 (설치·기동 진행 확인) -->
<dialog id="logs-modal" class="modal">
  <div class="modal-box max-w-3xl">
    <h3 id="logs-title" class="font-bold text-sm mb-2">컨테이너 로그</h3>
    <pre id="logs-body" class="bg-base-200 rounded p-3 text-xs overflow-x-auto max-h-96"></pre>
    <div class="modal-action">
      <form method="dialog"><button class="btn btn-sm">닫기</button></form>
    </div>
  </div>
  <form method="dialog" class="modal-backdrop"><button>close</button></form>
</dialog>

<script src="{{ root }}/static/js/tts.js?v={{ asset('js/tts.js') }}"></script>
{% endblock %}
```

주의: 기존 페이지(models.html 등)의 `<script>` 포함 방식·static 경로 프리픽스를 확인해 동일하게 맞출 것 (root 프리픽스 규칙이 다르면 그 관례를 따른다).

- [ ] **Step 5: 페이지 JS 작성**

`static/js/tts.js`:

```javascript
/* TTS 관리 페이지 로직. base: /admin/tts → API는 ../tts/* */
const TTS_API = '../tts';

let engines = [];        // 최신 엔진 상태 캐시
let pollTimer = null;    // 상태 폴링 (installing/starting이 있으면 짧게)
let logsTarget = null;   // 로그 모달이 보고 있는 엔진 id
let logsTimer = null;

function el(id) { return document.getElementById(id); }

const STATUS_BADGE = {
  not_installed: ['미설치', 'badge-ghost'],
  installing: ['설치 중...', 'badge-warning'],
  stopped: ['중지됨', 'badge-neutral'],
  starting: ['기동 중 (모델 로딩)', 'badge-warning'],
  running: ['실행 중', 'badge-success'],
  error: ['오류', 'badge-error'],
};

/* ---------- 엔진 카드 ---------- */

async function loadEngines() {
  try {
    const resp = await apiFetch(TTS_API + '/engines');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '조회 실패');
    engines = data.engines;
    el('engines-error').classList.add('hidden');
    renderEngines();
    renderTestPanel();
  } catch (e) {
    el('engines-error').classList.remove('hidden');
    el('engines-error').querySelector('span').textContent = e.message;
  }
  schedulePoll();
}

function schedulePoll() {
  clearTimeout(pollTimer);
  // 전이 상태(설치/기동 중)가 있으면 3초, 아니면 10초 간격
  const busy = engines.some(e => ['installing', 'starting'].includes(e.status));
  pollTimer = setTimeout(loadEngines, busy ? 3000 : 10000);
}

function renderEngines() {
  el('engine-cards').innerHTML = engines.map(e => {
    const [label, badge] = STATUS_BADGE[e.status] || [e.status, 'badge-ghost'];
    const buttons = [];
    if (e.status === 'not_installed' || e.status === 'error') {
      buttons.push(`<button class="btn btn-sm btn-primary" onclick="controlEngine('${e.id}','install')">설치</button>`);
    }
    if (e.status === 'stopped') {
      buttons.push(`<button class="btn btn-sm btn-primary" onclick="startEngine('${e.id}')">시작</button>`);
    }
    if (e.status === 'running' || e.status === 'starting') {
      buttons.push(`<button class="btn btn-sm" onclick="controlEngine('${e.id}','stop')">중지</button>`);
    }
    if (e.status !== 'not_installed') {
      buttons.push(`<button class="btn btn-sm btn-ghost" onclick="showLogs('${e.id}')">로그</button>`);
    }
    const installError = e.install_error
      ? `<div class="text-error text-xs mt-1">${escapeHtml(e.install_error)}</div>` : '';
    return `
      <div class="border border-base-300 rounded-lg p-4 space-y-2">
        <div class="flex items-center justify-between">
          <span class="font-semibold">${escapeHtml(e.name)}</span>
          <span class="badge badge-sm ${badge}">${label}</span>
        </div>
        <p class="text-xs opacity-70">${escapeHtml(e.description)}</p>
        <div class="text-xs opacity-60">언어: ${e.languages.join(', ')} · VRAM: ${escapeHtml(e.vram)}</div>
        ${installError}
        <div class="flex gap-2 pt-1">${buttons.join('')}</div>
      </div>`;
  }).join('');
}

async function controlEngine(id, action) {
  try {
    const resp = await apiFetch(`${TTS_API}/engines/${id}/${action}`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || action + ' 실패');
    engines = data.engines;
    renderEngines();
    renderTestPanel();
    schedulePoll();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function startEngine(id) {
  // 1개만 실행 정책 — 다른 엔진이 실행/기동 중이면 전환 확인
  const other = engines.find(e => e.id !== id && ['running', 'starting'].includes(e.status));
  if (other && !confirm(`${other.name}을(를) 중지하고 전환할까요?`)) return;
  controlEngine(id, 'start');
}

/* ---------- 로그 모달 ---------- */

async function refreshLogs() {
  if (!logsTarget) return;
  try {
    const resp = await apiFetch(`${TTS_API}/engines/${logsTarget}/logs`);
    const data = await resp.json();
    el('logs-body').textContent = resp.ok ? data.logs : (data.error || '로그 조회 실패');
  } catch (e) {
    el('logs-body').textContent = e.message;
  }
  logsTimer = setTimeout(refreshLogs, 3000);
}

function showLogs(id) {
  logsTarget = id;
  el('logs-title').textContent = `컨테이너 로그 — ${id}`;
  el('logs-body').textContent = '불러오는 중...';
  el('logs-modal').showModal();
  clearTimeout(logsTimer);
  refreshLogs();
}

el('logs-modal').addEventListener('close', () => {
  logsTarget = null;
  clearTimeout(logsTimer);
});

/* ---------- 합성 테스트 ---------- */

function renderTestPanel() {
  const running = engines.find(e => e.status === 'running');
  const badge = el('test-engine-badge');
  const select = el('tts-voice');
  if (!running) {
    badge.textContent = '실행 중 엔진 없음';
    badge.className = 'badge badge-ghost badge-sm';
    select.innerHTML = '<option>-</option>';
    el('tts-run').disabled = true;
    return;
  }
  badge.textContent = running.name;
  badge.className = 'badge badge-success badge-sm';
  el('tts-run').disabled = false;
  // 실행 엔진이 바뀌었을 때만 보이스 목록 재구성 (선택 유지)
  if (select.dataset.engine !== running.id) {
    select.dataset.engine = running.id;
    select.innerHTML = running.voices.map(v =>
      `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}</option>`).join('');
  }
}

el('tts-speed').addEventListener('input', () => {
  el('speed-value').textContent = Number(el('tts-speed').value).toFixed(1);
});

el('tts-run').addEventListener('click', async () => {
  const text = el('tts-text').value.trim();
  if (!text) { showToast('텍스트를 입력하세요', 'warning'); return; }
  const btn = el('tts-run');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span>합성 중...';
  try {
    const resp = await apiFetch(TTS_API, {
      method: 'POST',
      body: JSON.stringify({
        text,
        voice: el('tts-voice').value,
        speed: Number(el('tts-speed').value),
      }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.error || '합성 실패');
    }
    const url = URL.createObjectURL(await resp.blob());
    el('tts-result').classList.remove('hidden');
    el('tts-audio').src = url;
    el('tts-download').href = url;
    el('tts-audio').play();
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="play" class="size-4"></i>합성';
    if (window.lucide) lucide.createIcons();
  }
});

loadEngines();
```

- [ ] **Step 6: 테스트 통과 + 로컬 화면 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_admin_router.py -v`
Expected: 전체 passed

로컬에서 화면 렌더링 확인 (docker 없는 Mac에서는 엔진 상태가 error로 떠도 정상 — 페이지 구조·JS 오류만 확인):

```bash
cd suh-ai-server/flask && python3 app.py
# 브라우저에서 http://127.0.0.1:5000/admin/tts — 콘솔 에러 없는지, 카드 2개·테스트 패널 렌더링 확인
```

- [ ] **Step 7: 커밋**

```bash
git add suh-ai-server/flask/router/admin_router.py suh-ai-server/flask/templates/admin/base.html suh-ai-server/flask/templates/admin/tts.html suh-ai-server/flask/static/js/tts.js suh-ai-server/flask/test/test_admin_router.py
git commit -m "TTS 엔진 매니저 : feat : /admin/tts 관리 페이지 추가"
```

---

### Task 7: CosyVoice Docker 이미지 + CI 빌드 워크플로우

**Files:**
- Create: `suh-ai-server/docker/cosyvoice/Dockerfile`
- Create: `.github/workflows/SUH-AI-TTS-IMAGE.yaml`

**Interfaces:**
- Consumes: DockerHub 시크릿 `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (Task 8에서 등록)
- Produces: DockerHub 이미지 `cassiiopeia/suh-tts-cosyvoice:latest` — 컨테이너 기동 시 fastapi 서버가 :50000에서 대기, 모델은 첫 기동 때 `/root/.cache`(볼륨)에 자동 다운로드

- [ ] **Step 1: Dockerfile 작성**

`suh-ai-server/docker/cosyvoice/Dockerfile`:

```dockerfile
# CosyVoice fastapi 서빙 이미지 — 공식 runtime Dockerfile 기반, CMD만 명시
# 모델 가중치는 이미지에 굽지 않는다: 첫 기동 시 modelscope가 받아 /root/.cache 볼륨에 캐시
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends git git-lfs unzip g++ && \
    git lfs install && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice
WORKDIR /opt/CosyVoice
RUN pip3 install --no-cache-dir -r requirements.txt

# Fun-CosyVoice3 전환은 이 env만 교체 (예: iic/Fun-CosyVoice3-0.5B-2512)
ENV MODEL_DIR=iic/CosyVoice2-0.5B
EXPOSE 50000
CMD ["sh", "-c", "python3 runtime/python/fastapi/server.py --port 50000 --model_dir ${MODEL_DIR}"]
```

- [ ] **Step 2: 빌드 워크플로우 작성**

`.github/workflows/SUH-AI-TTS-IMAGE.yaml`:

```yaml
# =========================================
# CosyVoice TTS 서빙 이미지 빌드·배포
# =========================================
# docker/cosyvoice/** 변경 시에만 빌드 (이미지가 커서 매 push 빌드는 낭비)
# 최초 1회는 workflow_dispatch로 수동 실행

name: SUH-AI-TTS-IMAGE

on:
  push:
    branches: [ "main" ]
    paths:
      - "suh-ai-server/docker/cosyvoice/**"
  workflow_dispatch:

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - name: 소스 체크아웃
        uses: actions/checkout@v4

      - name: Docker Buildx 설정
        uses: docker/setup-buildx-action@v3

      - name: DockerHub 로그인
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: 이미지 빌드 및 push (latest + sha 태그)
        uses: docker/build-push-action@v6
        with:
          context: suh-ai-server/docker/cosyvoice
          push: true
          tags: |
            cassiiopeia/suh-tts-cosyvoice:latest
            cassiiopeia/suh-tts-cosyvoice:${{ github.sha }}
```

- [ ] **Step 3: YAML 문법 검증**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/SUH-AI-TTS-IMAGE.yaml'))" && echo OK`
Expected: `OK`

(Docker가 로컬에 있으면 추가 검증: `docker build -t cosyvoice-test suh-ai-server/docker/cosyvoice` — 없으면 CI 첫 실행이 검증을 대신한다)

- [ ] **Step 4: 커밋**

```bash
git add suh-ai-server/docker/cosyvoice/Dockerfile .github/workflows/SUH-AI-TTS-IMAGE.yaml
git commit -m "TTS 엔진 매니저 : chore : CosyVoice 서빙 이미지 및 CI 빌드 워크플로우 추가"
```

---

### Task 8: 배포 스크립트 + 시크릿 등록

**Files:**
- Create: `suh-ai-server/scripts/deploy-tts.ps1`
- Modify: `.github/workflows/SUH-AI-PROJECT-CONTROL.yaml` (deploy 단계 추가)

**Interfaces:**
- Consumes: 기존 deploy job의 SSH 시크릿(`SERVER_HOST/USER/PASSWORD`, 포트 2023), 서버의 Docker Desktop
- Produces: 배포 시 GPU 패스스루 검증 + `suh-tts-models` 볼륨 준비 (실패해도 본 배포는 막지 않음)

- [ ] **Step 1: deploy-tts.ps1 작성**

`suh-ai-server/scripts/deploy-tts.ps1`:

```powershell
# =========================================
# TTS 엔진 사전준비 — GPU 패스스루 검증 + 모델 캐시 볼륨 생성
# =========================================
# TTS는 부가 기능이므로 어떤 실패도 본 배포를 막지 않는다 (경고 로그 후 exit 0)

Write-Host "=== [deploy-tts] TTS 사전준비 시작 ==="

# 1. Docker 데몬 확인
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[deploy-tts] WARN: Docker 데몬이 응답하지 않습니다 - Docker Desktop 상태 확인 필요. 건너뜁니다."
    exit 0
}

# 2. 모델 캐시 볼륨 (이미 있으면 no-op)
docker volume create suh-tts-models | Out-Null
Write-Host "[deploy-tts] 모델 캐시 볼륨 suh-tts-models 준비 완료"

# 3. GPU 패스스루 검증 — 실패하면 TTS 컨테이너가 GPU를 못 쓴다는 뜻
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
if ($LASTEXITCODE -ne 0) {
    Write-Host "[deploy-tts] WARN: GPU 패스스루 실패 - NVIDIA 드라이버의 WSL2 지원(최신 Game Ready/Studio 드라이버) 확인 필요"
    exit 0
}

Write-Host "=== [deploy-tts] 완료: GPU 패스스루 정상 ==="
exit 0
```

- [ ] **Step 2: 배포 워크플로우에 단계 추가**

`.github/workflows/SUH-AI-PROJECT-CONTROL.yaml`의 마지막 SSH 단계(deploy-flask.ps1 실행, 약 130-138행) 바로 아래에 동일 형식으로 추가:

```yaml
      - name: TTS 사전준비 스크립트 실행
        uses: appleboy/ssh-action@v1.1.0
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          port: 2023
          password: ${{ secrets.SERVER_PASSWORD }}
          script: |
            powershell -ExecutionPolicy Bypass -File "C:\AI\suh-ai-server\scripts\deploy-tts.ps1"
```

(들여쓰기·`with` 키 구성은 기존 단계와 완전히 동일하게 맞출 것 — 수정 전 해당 블록을 Read로 확인)

- [ ] **Step 3: YAML 문법 검증**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/SUH-AI-PROJECT-CONTROL.yaml'))" && echo OK`
Expected: `OK`

- [ ] **Step 4: DockerHub 시크릿 등록**

`/cassiiopeia:suh-github` 스킬로 Actions Secret 등록 (gh CLI 금지 규칙):
- `DOCKERHUB_USERNAME` = `cassiiopeia`
- `DOCKERHUB_TOKEN` = **사용자에게 요청** — DockerHub Access Token(Read/Write)을 새로 발급해 달라고 안내 (2026-07-13 설계에서 기존 토큰이 채팅에 노출돼 재발급 권장된 상태)

이 단계는 사용자 입력 없이는 완료할 수 없다 — 토큰을 받을 때까지 대기하고, 나머지 Task를 먼저 진행해도 된다.

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/scripts/deploy-tts.ps1 .github/workflows/SUH-AI-PROJECT-CONTROL.yaml
git commit -m "TTS 엔진 매니저 : chore : deploy-tts 사전준비 스크립트 및 배포 단계 추가"
```

---

### Task 9: 배포 및 서버 스모크 테스트

**Files:** 없음 (검증 전용)

**Interfaces:**
- Consumes: Task 1-8 전부, 서버 관리자 화면

- [ ] **Step 1: push 허락 요청**

전체 테스트 최종 확인 후 **사용자에게 push 허락을 명시적으로 요청**한다 (금지 규칙: 허락 없이 push 불가). 브랜치 전략은 사용자에게 확인 (develop → main 흐름 여부).

```bash
cd suh-ai-server/flask && python3 -m pytest test/ -v   # 전체 회귀 최종 확인
```

- [ ] **Step 2: CosyVoice 이미지 빌드 실행 확인**

push 후 `/cassiiopeia:suh-github` 스킬로 `SUH-AI-TTS-IMAGE` 워크플로우 실행 상태 확인 (최초는 workflow_dispatch 수동 트리거). 빌드 성공 시 DockerHub에 `cassiiopeia/suh-tts-cosyvoice:latest` 존재 확인.

- [ ] **Step 3: 배포 파이프라인 확인**

main 반영은 `/cassiiopeia:suh-changelog-deploy` 스킬 규칙을 따른다 (main push만으로는 배포되지 않음 — deploy 브랜치 push가 트리거). 배포 로그에서 `[deploy-tts]` 출력 확인:
- `GPU 패스스루 정상` → 진행
- `WARN: GPU 패스스루 실패` → 사용자에게 서버 NVIDIA 드라이버 업데이트 안내 후 재배포

- [ ] **Step 4: 관리자 화면 스모크 테스트 (사용자와 함께)**

체크리스트 — `https://<서버>/admin/tts`에서:
1. 엔진 카드 2개(Kokoro/CosyVoice) 표시, 상태 `미설치`
2. Kokoro 설치 → `설치 중...` → `중지됨` 전이 확인
3. Kokoro 시작 → `기동 중` → `실행 중` 전이, 로그 모달에서 기동 로그 확인
4. 영어 텍스트 합성 → 오디오 재생 + WAV 다운로드
5. CosyVoice 설치·시작 (첫 기동은 모델 다운로드로 수 분 소요 — 로그 모달로 진행 확인, Kokoro 자동 중지 확인)
6. 한국어 텍스트 합성 → 재생 품질 확인 (음높이가 이상하면 `sample_rate` 24000 → 22050 조정 검토)
7. `MODEL_DIR=iic/Fun-CosyVoice3-0.5B-2512` env 교체 재기동 시도 — 성공 시 품질 비교, 실패 시 CosyVoice2 유지 (레지스트리 name도 실제 모델과 일치하게 갱신)
8. Swagger(`/docs/swagger`)에서 `POST /tts` 외부 호출 테스트

- [ ] **Step 5: 문서 갱신**

README의 AI API 표에 `/tts` 행 추가 + 스모크 테스트에서 확정된 사실(최종 모델, sample_rate)을 스펙 문서에 반영 후 커밋:

```bash
git add README.md docs/superpowers/specs/2026-07-17-tts-engine-manager-design.md
git commit -m "TTS 엔진 매니저 : docs : README API 표 및 스펙 확정 사항 반영"
```

---

## Self-Review 결과

- **스펙 커버리지**: 레지스트리·어댑터(Task 1-2), 수명주기·1개 실행 정책(Task 3), 외부 API·감사로그(Task 4), Swagger(Task 5), 관리자 페이지·전환 확인 모달·로그 스트리밍(Task 6), 이미지 빌드(Task 7), deploy-tts.ps1·GPU 검증·볼륨(Task 8), 스모크 테스트(Task 9) — 전부 매핑됨
- **모델 선택 편차**: 스펙은 Fun-CosyVoice3를 명시했으나 구현 초기값은 검증된 `iic/CosyVoice2-0.5B`로 시작, Task 9 Step 4-7에서 전환 시도 — Global Constraints에 명시
- **타입 일관성**: `TtsService.install/start/stop(engine_id)` 시그니처가 라우터의 `getattr(tts_service, action)(engine_id)`와 일치, 어댑터 시그니처 `(text, voice, speed)` 전 Task 동일, 상태 문자열 6종(`not_installed|installing|stopped|starting|running|error`)이 서비스·JS STATUS_BADGE에서 일치
