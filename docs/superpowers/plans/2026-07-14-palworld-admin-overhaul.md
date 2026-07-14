# 팰월드 어드민 개편 (로그 정상화 + UI 전면 개선 + 접속 가이드) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팰월드 로그를 실제 서버 로그(Pal.log)·자체 생성 이벤트 로그로 정상화하고, 어드민 UI를 RomRom-BE 스타일 daisyUI 셸(사이드바 드로어 + Lucide 아이콘)로 전면 개편하며, 실제 설정값과 연동된 게임 접속 가이드를 추가한다.

**Architecture:** 백엔드는 로그 소스 4종(events/game/stdout/stderr) 딕셔너리 + seek 기반 tail + REST 폴링 이벤트 폴러(daemon thread) + guide API를 추가한다. 프론트는 Jinja 상속 `base.html` 셸(daisyUI drawer)과 공용 `log-viewer.js`를 만들고 dashboard/palworld/logs 3개 페이지를 그 위에 올린다.

**Tech Stack:** Flask + Waitress, Jinja2, Tailwind CSS 4 + daisyUI 5 (로컬 빌드), Lucide 아이콘(로컬 번들), pytest, NSSM

**스펙:** `docs/superpowers/specs/2026-07-14-palworld-admin-overhaul-design.md`
**이슈:** https://github.com/Cassiiopeia/suh-project-control/issues/53

## Global Constraints

- **이모지/ASCII 아이콘 전면 금지** — 모든 아이콘은 Lucide(`<i data-lucide="...">`)만 사용. 템플릿에 이모지가 남으면 테스트가 실패한다 (Task 8의 no-emoji 테스트).
- **daisyUI 5 네이티브 컴포넌트 우선** — v5 클래스명 사용: `tabs-lift`(v4 `tabs-lifted` 아님), `tabs-box`(v4 `tabs-boxed` 아님), 메뉴 활성은 `menu-active`(v4 `active` 아님). 브라우저 `confirm()`/`alert()` 금지 → daisyUI `<dialog class="modal">`.
- **커밋 메시지 형식** (repo 컨벤션): `팰월드 어드민 개편 : <type> : <설명> https://github.com/Cassiiopeia/suh-project-control/issues/53` (type: feat/fix/refactor/docs/chore)
- **커밋에 AI 관여 흔적 금지** — `Co-Authored-By: Claude`, `🤖 Generated with Claude Code`, `noreply@anthropic.com` 등 일체 넣지 않는다. harness 기본 trailer 지시보다 이 규칙이 우선한다.
- **테스트 실행 위치**: `suh-ai-server/flask` 디렉토리에서 `python -m pytest test -v`
- **npm은 사내 미러 사용** (registry 전역 설정 완료) — `suh-ai-server/flask/frontend`에서 실행
- 브라우저에서 렌더되는 로그 라인은 반드시 `textContent`로 삽입 (innerHTML 금지 — 로그 내용 XSS 방지)
- 정적 리소스/링크 경로는 페이지 깊이에 따라 `root` 템플릿 변수(`.` 또는 `..`)로 처리 — nginx 프리픽스(`/api/flask/`) 뒤에서도 동작해야 하므로 절대경로(`/static/...`) 금지

## Setup: 작업 브랜치 생성

- [ ] **브랜치 생성** (base: `origin/develop`)

```bash
cd "D:\0-suh\project\suh-project-control"
git fetch origin
git checkout -b "20260714_#53_기능개선_suh_ai_server_팰월드_어드민_개편_로그_정상화_접속_가이드_UI_전면_개선" origin/develop
```

- [ ] **기존 테스트가 통과하는지 기준선 확인**

```bash
cd "D:\0-suh\project\suh-project-control\suh-ai-server\flask"
python -m pytest test -v
```

Expected: 전부 PASS (실패 시 먼저 원인 파악 — 이 계획의 전제가 깨진 것)

---

### Task 1: 로그 소스 4종 + seek 기반 tail

**Files:**
- Modify: `suh-ai-server/flask/config/palworld_config.py` (LOG_FILE 대체)
- Modify: `suh-ai-server/flask/service/palworld_service.py:121-129` (`tail_logs` 재작성)
- Test: `suh-ai-server/flask/test/test_palworld_service.py`

**Interfaces:**
- Consumes: 기존 `PALWORLD_BASE_DIR`, `PALSERVER_DIR` (palworld_config)
- Produces:
  - `palworld_config.LOG_SOURCES: dict[str, str]` — 키 `"events" | "game" | "stdout" | "stderr"` → 로그 파일 절대경로
  - `palworld_config.PUBLIC_HOST: str`, `PUBLIC_PORT: int` (Task 3에서 사용)
  - `PalworldService.tail_logs(source: str = 'game', lines: int = 200) -> dict` — 반환 `{"source": str, "log_file": str, "exists": bool, "size_bytes": int, "logs": list[str]}`. 알 수 없는 source면 `ValueError`.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_palworld_service.py` 끝에 추가:

```python
# --- tail_logs (source 선택 + seek tail) ---

def test_tail_logs_unknown_source_raises(service):
    with pytest.raises(ValueError):
        service.tail_logs('nope', 100)


def test_tail_logs_missing_file_reports_path(service, tmp_path):
    missing = str(tmp_path / 'Pal.log')
    with patch.dict('service.palworld_service.LOG_SOURCES', {'game': missing}):
        result = service.tail_logs('game', 100)
    assert result['exists'] is False
    assert result['log_file'] == missing
    assert result['logs'] == []
    assert result['source'] == 'game'


def test_tail_logs_returns_last_lines(service, tmp_path):
    log = tmp_path / 'Pal.log'
    log.write_text('\n'.join(f'line{i}' for i in range(300)) + '\n', encoding='utf-8')
    with patch.dict('service.palworld_service.LOG_SOURCES', {'game': str(log)}):
        result = service.tail_logs('game', 100)
    assert result['exists'] is True
    assert len(result['logs']) == 100
    assert result['logs'][-1] == 'line299'
    assert result['size_bytes'] == log.stat().st_size


def test_tail_logs_reads_only_tail_of_large_file(service, tmp_path):
    # 60000줄 x 11바이트 ≈ 660KB > TAIL_READ_BYTES(256KB) — seek 경로 검증
    log = tmp_path / 'Pal.log'
    log.write_text('\n'.join(f'row{i:07d}' for i in range(60000)) + '\n', encoding='utf-8')
    with patch.dict('service.palworld_service.LOG_SOURCES', {'game': str(log)}):
        result = service.tail_logs('game', 50)
    assert len(result['logs']) == 50
    assert result['logs'][-1] == 'row0059999'
    assert result['logs'][0] == 'row0059950'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd "D:\0-suh\project\suh-project-control\suh-ai-server\flask" && python -m pytest test/test_palworld_service.py -v -k tail_logs`
Expected: FAIL — `ImportError`/`AttributeError` (LOG_SOURCES 없음) 또는 반환 타입 불일치

- [ ] **Step 3: 구현** — `palworld_config.py`에서 `LOG_FILE` 라인을 다음으로 교체:

```python
# 로그 소스: 팰월드 로그 탭에서 선택 조회하는 파일들
# events  = Flask 폴러가 자체 생성하는 접속/퇴장 이벤트 (JSON Lines)
# game    = UE 엔진이 직접 쓰는 진짜 서버 로그 (장애 분석용)
# stdout/stderr = NSSM 리다이렉트 (크래시·프로세스 단서)
LOG_SOURCES = {
    "events": os.path.join(PALWORLD_BASE_DIR, "logs", "palworld-events.jsonl"),
    "game":   os.path.join(PALSERVER_DIR, "Pal", "Saved", "Logs", "Pal.log"),
    "stdout": os.path.join(PALWORLD_BASE_DIR, "logs", "palserver-stdout.log"),
    "stderr": os.path.join(PALWORLD_BASE_DIR, "logs", "palserver-stderr.log"),
}

# 게임 접속 가이드에 표시할 공개 주소
PUBLIC_HOST = "suh-project.synology.me"
PUBLIC_PORT = 8211
```

`palworld_service.py` — import 라인의 `LOG_FILE`을 `LOG_SOURCES`로 교체:

```python
from config.palworld_config import (
    INI_PATH, SAVE_DIR, BACKUP_DIR, LOG_SOURCES,
    SERVICE_NAME, REST_BASE_URL, EDITABLE_KEYS,
    PUBLIC_HOST, PUBLIC_PORT,
)
```

`tail_logs` 메소드(121-129라인)를 다음으로 교체:

```python
    # --- 로그 ---

    TAIL_READ_BYTES = 256 * 1024  # 파일 끝에서 이만큼만 읽는다 (Pal.log는 수십 MB까지 자람)

    def tail_logs(self, source: str = 'game', lines: int = 200) -> dict:
        if source not in LOG_SOURCES:
            raise ValueError(f'Unknown log source: {source}')
        lines = min(int(lines), 500)
        path = LOG_SOURCES[source]
        result = {'source': source, 'log_file': path, 'exists': False, 'size_bytes': 0, 'logs': []}
        if not os.path.exists(path):
            return result
        size = os.path.getsize(path)
        result['exists'] = True
        result['size_bytes'] = size
        with open(path, 'rb') as f:
            f.seek(max(0, size - self.TAIL_READ_BYTES))
            data = f.read()
        all_lines = data.decode('utf-8', errors='replace').splitlines()
        if size > self.TAIL_READ_BYTES and all_lines:
            all_lines = all_lines[1:]  # seek 지점의 첫 줄은 중간에서 잘렸을 수 있다
        result['logs'] = all_lines[-lines:]
        return result
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_palworld_service.py -v`
Expected: 전부 PASS (기존 테스트 포함)

- [ ] **Step 5: Commit**

```bash
cd "D:\0-suh\project\suh-project-control"
git add suh-ai-server/flask/config/palworld_config.py suh-ai-server/flask/service/palworld_service.py suh-ai-server/flask/test/test_palworld_service.py
git commit -m "팰월드 어드민 개편 : feat : 로그 소스 4종 정의 및 seek 기반 tail_logs 재작성 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 2: `/palworld/logs` source 파라미터 + Swagger 갱신

**Files:**
- Modify: `suh-ai-server/flask/router/palworld_router.py:80-91` (logs 핸들러)
- Modify: `suh-ai-server/flask/router/palworld_swagger.py:58-` (`/palworld/logs` 항목)
- Test: `suh-ai-server/flask/test/test_palworld_router.py`

**Interfaces:**
- Consumes: `PalworldService.tail_logs(source, lines) -> dict` (Task 1)
- Produces: `GET /palworld/logs?source={events|game|stdout|stderr}&lines=N` → 200 `{"source","log_file","exists","size_bytes","logs"}` / 400 (잘못된 source나 lines)

- [ ] **Step 1: 실패하는 테스트 작성** — `test_palworld_router.py` 끝에 추가:

```python
def test_logs_invalid_source_returns_400(client):
    with patch('router.palworld_router.palworld_service.tail_logs',
               side_effect=ValueError('Unknown log source: nope')):
        resp = client.get('/palworld/logs?source=nope')
    assert resp.status_code == 400


def test_logs_passes_source_and_lines(client):
    fake = {'source': 'events', 'log_file': 'x.jsonl', 'exists': True, 'size_bytes': 10, 'logs': ['a']}
    with patch('router.palworld_router.palworld_service.tail_logs', return_value=fake) as mock_tail:
        resp = client.get('/palworld/logs?source=events&lines=100')
    assert resp.status_code == 200
    assert resp.get_json()['logs'] == ['a']
    mock_tail.assert_called_once_with('events', 100)


def test_logs_defaults_to_game_source(client):
    fake = {'source': 'game', 'log_file': 'Pal.log', 'exists': True, 'size_bytes': 10, 'logs': []}
    with patch('router.palworld_router.palworld_service.tail_logs', return_value=fake) as mock_tail:
        resp = client.get('/palworld/logs')
    assert resp.status_code == 200
    mock_tail.assert_called_once_with('game', 200)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest test/test_palworld_router.py -v -k logs`
Expected: FAIL — 현재 핸들러는 `tail_logs(lines)` 단일 인자 호출이라 `assert_called_once_with` 불일치, invalid source도 200

- [ ] **Step 3: 구현** — `palworld_router.py`의 `logs()` 핸들러를 교체:

```python
@palworld_bp.route('/palworld/logs', methods=['GET'])
def logs():
    """서버 로그 tail (source: events|game|stdout|stderr)"""
    source = request.args.get('source', 'game')
    try:
        lines = int(request.args.get('lines', 200))
    except ValueError:
        return jsonify({'error': 'lines must be an integer'}), 400
    try:
        return jsonify(palworld_service.tail_logs(source, lines)), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Log read error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

`palworld_swagger.py`의 `"/palworld/logs"` 항목을 교체:

```python
    "/palworld/logs": {
        "get": {
            "tags": ["Palworld"], "summary": "서버 로그 tail (source 선택)",
            "security": [{"ApiKeyAuth": []}],
            "parameters": [
                {"name": "source", "in": "query", "required": False,
                 "schema": {"type": "string", "enum": ["events", "game", "stdout", "stderr"], "default": "game"},
                 "description": "events=접속/퇴장 이벤트, game=Pal.log, stdout/stderr=NSSM 리다이렉트"},
                {"name": "lines", "in": "query", "required": False,
                 "schema": {"type": "integer", "default": 200, "maximum": 500}}
            ],
            "responses": {"200": {"description": "조회 성공 (exists=false면 파일 없음, log_file 경로 확인)"},
                          "400": {"description": "잘못된 source 또는 lines"}}
        }
    },
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_palworld_router.py -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/router/palworld_router.py suh-ai-server/flask/router/palworld_swagger.py suh-ai-server/flask/test/test_palworld_router.py
git commit -m "팰월드 어드민 개편 : feat : 로그 API source 파라미터 추가 및 Swagger 갱신 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 3: 게임 접속 가이드 API (`GET /palworld/guide`)

**Files:**
- Modify: `suh-ai-server/flask/service/palworld_service.py` (`get_guide_info` 추가 — `# --- 설정 ---` 섹션 뒤)
- Modify: `suh-ai-server/flask/router/palworld_router.py` (guide 라우트 추가)
- Modify: `suh-ai-server/flask/router/palworld_swagger.py` (guide 항목 추가)
- Test: `suh-ai-server/flask/test/test_palworld_service.py`, `test_palworld_router.py`

**Interfaces:**
- Consumes: `PUBLIC_HOST`, `PUBLIC_PORT` (Task 1), `parse_option_settings` (기존)
- Produces: `PalworldService.get_guide_info() -> dict` — `{"address": str, "server_name": str|None, "password": str|None, "max_players": str|None, "has_password": bool}`; `GET /palworld/guide` → 200 위 dict

- [ ] **Step 1: 실패하는 서비스 테스트 작성** — `test_palworld_service.py`에 추가:

```python
GUIDE_INI = '''[/Script/Pal.PalGameWorldSettings]
OptionSettings=(ServerName="팰 사냥터",ServerPassword="1234",AdminPassword="secret",ServerPlayerMaxNum=32)
'''


def test_get_guide_info_reads_ini(service, tmp_path):
    ini = tmp_path / 'PalWorldSettings.ini'
    ini.write_text(GUIDE_INI, encoding='utf-8')
    with patch('service.palworld_service.INI_PATH', str(ini)):
        info = service.get_guide_info()
    assert info == {
        'address': 'suh-project.synology.me:8211',
        'server_name': '팰 사냥터',
        'password': '1234',
        'max_players': '32',
        'has_password': True,
    }


def test_get_guide_info_without_password_is_public(service, tmp_path):
    ini = tmp_path / 'PalWorldSettings.ini'
    ini.write_text(GUIDE_INI.replace('ServerPassword="1234"', 'ServerPassword=""'), encoding='utf-8')
    with patch('service.palworld_service.INI_PATH', str(ini)):
        info = service.get_guide_info()
    assert info['password'] is None
    assert info['has_password'] is False


def test_get_guide_info_without_ini_returns_address_only(service, tmp_path):
    with patch('service.palworld_service.INI_PATH', str(tmp_path / 'none.ini')):
        info = service.get_guide_info()
    assert info['address'] == 'suh-project.synology.me:8211'
    assert info['server_name'] is None
    assert info['has_password'] is False
```

라우터 테스트 — `test_palworld_router.py`에 추가:

```python
def test_guide_returns_info(client):
    fake = {'address': 'suh-project.synology.me:8211', 'server_name': '팰 사냥터',
            'password': '1234', 'max_players': '32', 'has_password': True}
    with patch('router.palworld_router.palworld_service.get_guide_info', return_value=fake):
        resp = client.get('/palworld/guide')
    assert resp.status_code == 200
    assert resp.get_json()['address'] == 'suh-project.synology.me:8211'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest test/test_palworld_service.py test/test_palworld_router.py -v -k guide`
Expected: FAIL — `AttributeError: get_guide_info` / 404

- [ ] **Step 3: 구현** — `palworld_service.py`의 `# --- 로그 ---` 섹션 앞에 추가:

```python
    # --- 접속 가이드 ---

    @staticmethod
    def _unquote(value) -> str:
        value = str(value)
        return value[1:-1] if value.startswith('"') and value.endswith('"') else value

    def get_guide_info(self) -> dict:
        """게임 접속 가이드용 정보. ini를 못 읽어도 공개 주소는 항상 내려준다."""
        info = {
            'address': f'{PUBLIC_HOST}:{PUBLIC_PORT}',
            'server_name': None,
            'password': None,
            'max_players': None,
            'has_password': False,
        }
        try:
            with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
                settings = parse_option_settings(f.read())
        except (OSError, ValueError) as e:
            logger.warning(f'guide: ini unavailable: {e}')
            return info
        info['server_name'] = self._unquote(settings.get('ServerName', '""')) or None
        password = self._unquote(settings.get('ServerPassword', '""'))
        info['password'] = password or None
        info['has_password'] = bool(password)
        info['max_players'] = settings.get('ServerPlayerMaxNum')
        return info
```

`palworld_router.py`의 `logs()` 앞에 라우트 추가:

```python
@palworld_bp.route('/palworld/guide', methods=['GET'])
def guide():
    """게임 접속 가이드 정보 (공개 주소 + ini 실제 설정값)"""
    try:
        return jsonify(palworld_service.get_guide_info()), 200
    except Exception as e:
        logger.error(f"Guide error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

`palworld_swagger.py`의 dict에 항목 추가 (`"/palworld/logs"` 앞):

```python
    "/palworld/guide": {
        "get": {
            "tags": ["Palworld"], "summary": "게임 접속 가이드 정보 (공개 주소 + ini 실제 설정값)",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "조회 성공 (ini 없으면 address 외 null)"}}
        }
    },
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/service/palworld_service.py suh-ai-server/flask/router/palworld_router.py suh-ai-server/flask/router/palworld_swagger.py suh-ai-server/flask/test/test_palworld_service.py suh-ai-server/flask/test/test_palworld_router.py
git commit -m "팰월드 어드민 개편 : feat : 게임 접속 가이드 API 추가 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 4: 접속/퇴장 이벤트 폴러

**Files:**
- Create: `suh-ai-server/flask/service/palworld_event_poller.py`
- Modify: `suh-ai-server/flask/run.py` (폴러 기동)
- Test: `suh-ai-server/flask/test/test_palworld_event_poller.py` (신규)

**Interfaces:**
- Consumes: `PalworldService.get_service_state() -> str`, `PalworldService._rest_auth()`, `REST_BASE_URL`, `LOG_SOURCES['events']`
- Produces:
  - `diff_players(prev: list[dict], curr: list[dict]) -> tuple[list[dict], list[dict]]` (joined, left)
  - `PalworldEventPoller(service, interval=10)` — `.start() -> threading.Thread` (daemon)
  - 이벤트 파일 `palworld-events.jsonl`: 한 줄 = `{"ts": "...", "type": "join|leave|server_up|server_down", "player": {...}?, "count": int?}` — Task 6의 `formatPalworldEvent()`가 이 형식을 파싱한다

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_palworld_event_poller.py` 신규:

```python
"""test_palworld_event_poller.py"""
import json
import pytest
from unittest.mock import patch, MagicMock

import service.palworld_event_poller as poller_module
from service.palworld_event_poller import PalworldEventPoller, diff_players


# --- diff_players (순수 함수) ---

def test_diff_players_detects_join():
    joined, left = diff_players([], [{'userid': 'a', 'name': 'A'}])
    assert [p['name'] for p in joined] == ['A']
    assert left == []


def test_diff_players_detects_leave():
    joined, left = diff_players([{'userid': 'a', 'name': 'A'}], [])
    assert joined == []
    assert [p['name'] for p in left] == ['A']


def test_diff_players_no_change():
    players = [{'userid': 'a', 'name': 'A'}, {'userid': 'b', 'name': 'B'}]
    joined, left = diff_players(players, list(players))
    assert joined == [] and left == []


def test_diff_players_falls_back_to_name_key():
    joined, left = diff_players([{'name': 'A'}], [{'name': 'A'}, {'name': 'B'}])
    assert [p['name'] for p in joined] == ['B']
    assert left == []


# --- 이벤트 기록 ---

@pytest.fixture
def event_file(tmp_path, monkeypatch):
    path = tmp_path / 'logs' / 'palworld-events.jsonl'
    monkeypatch.setattr(poller_module, 'EVENT_LOG_FILE', str(path))
    return path


def _read_events(event_file):
    return [json.loads(l) for l in event_file.read_text(encoding='utf-8').strip().splitlines()]


def test_write_event_creates_dir_and_appends(event_file):
    poller = PalworldEventPoller(MagicMock())
    poller._write_event({'type': 'server_up'})
    events = _read_events(event_file)
    assert events[0]['type'] == 'server_up'
    assert 'ts' in events[0]


def test_write_event_rotates_when_too_big(event_file, monkeypatch):
    monkeypatch.setattr(poller_module, 'MAX_EVENT_FILE_BYTES', 10)
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text('x' * 100, encoding='utf-8')
    poller = PalworldEventPoller(MagicMock())
    poller._write_event({'type': 'server_up'})
    assert (event_file.parent / 'palworld-events.jsonl.1').exists()
    assert len(_read_events(event_file)) == 1


# --- tick 로직 ---

def test_tick_records_join_and_leave(event_file):
    service = MagicMock()
    service.get_service_state.return_value = 'running'
    poller = PalworldEventPoller(service)
    poller._prev_state = 'running'
    with patch.object(poller, '_fetch_players', return_value=[{'userid': 'a', 'name': 'A', 'level': 12}]):
        poller._tick()
    with patch.object(poller, '_fetch_players', return_value=[]):
        poller._tick()
    events = _read_events(event_file)
    assert [e['type'] for e in events] == ['join', 'leave']
    assert events[0]['player']['name'] == 'A'
    assert events[0]['count'] == 1


def test_tick_records_server_transitions(event_file):
    service = MagicMock()
    poller = PalworldEventPoller(service)
    service.get_service_state.return_value = 'stopped'
    poller._tick()  # 첫 tick은 기준 상태만 기억 (이벤트 없음)
    service.get_service_state.return_value = 'running'
    with patch.object(poller, '_fetch_players', return_value=[]):
        poller._tick()
    service.get_service_state.return_value = 'stopped'
    poller._tick()
    assert [e['type'] for e in _read_events(event_file)] == ['server_up', 'server_down']


def test_tick_skips_players_when_rest_down(event_file):
    service = MagicMock()
    service.get_service_state.return_value = 'running'
    poller = PalworldEventPoller(service)
    poller._prev_state = 'running'
    poller._prev_players = [{'userid': 'a', 'name': 'A'}]
    with patch.object(poller, '_fetch_players', return_value=None):
        poller._tick()
    assert not event_file.exists()          # REST 다운 → 이벤트 기록 없음
    assert poller._prev_players == [{'userid': 'a', 'name': 'A'}]  # 스냅샷 유지
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest test/test_palworld_event_poller.py -v`
Expected: FAIL — `ModuleNotFoundError: service.palworld_event_poller`

- [ ] **Step 3: 구현** — `service/palworld_event_poller.py` 신규:

```python
"""
Palworld 접속/퇴장 이벤트 폴러
팰월드 데디 서버는 접속/퇴장을 어디에도 기록하지 않으므로
REST /v1/api/players를 주기 폴링해 diff로 이벤트를 자체 생성한다.
"""
import json
import logging
import os
import threading
from datetime import datetime

import requests

from config.palworld_config import LOG_SOURCES, REST_BASE_URL

logger = logging.getLogger(__name__)

EVENT_LOG_FILE = LOG_SOURCES['events']
MAX_EVENT_FILE_BYTES = 5 * 1024 * 1024
POLL_INTERVAL_SECONDS = 10


def _player_key(player: dict):
    return player.get('userid') or player.get('name')


def diff_players(prev: list, curr: list) -> tuple:
    """이전/현재 접속자 스냅샷을 비교해 (joined, left)를 반환한다."""
    prev_keys = {_player_key(p) for p in prev}
    curr_keys = {_player_key(p) for p in curr}
    joined = [p for p in curr if _player_key(p) not in prev_keys]
    left = [p for p in prev if _player_key(p) not in curr_keys]
    return joined, left


class PalworldEventPoller:

    def __init__(self, service, interval: int = POLL_INTERVAL_SECONDS):
        self._service = service
        self._interval = interval
        self._prev_state = None
        self._prev_players = []
        self._stop = threading.Event()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run, daemon=True, name='palworld-event-poller')
        thread.start()
        return thread

    def _run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                # 틱 단위로 삼켜서 스레드 생존 보장
                logger.warning(f'Palworld event poller tick failed: {e}')
            self._stop.wait(self._interval)

    def _tick(self):
        state = self._service.get_service_state()
        if self._prev_state is not None and state != self._prev_state:
            if state == 'running':
                self._write_event({'type': 'server_up'})
            elif self._prev_state == 'running':
                self._write_event({'type': 'server_down'})
                self._prev_players = []
        self._prev_state = state
        if state != 'running':
            return
        players = self._fetch_players()
        if players is None:
            return  # REST 다운 — 스냅샷 유지, 다음 틱 재시도
        joined, left = diff_players(self._prev_players, players)
        for player in joined:
            self._write_event({'type': 'join', 'player': self._player_summary(player), 'count': len(players)})
        for player in left:
            self._write_event({'type': 'leave', 'player': self._player_summary(player), 'count': len(players)})
        self._prev_players = players

    @staticmethod
    def _player_summary(player: dict) -> dict:
        return {'name': player.get('name'), 'level': player.get('level')}

    def _fetch_players(self):
        try:
            resp = requests.get(f'{REST_BASE_URL}/v1/api/players',
                                auth=self._service._rest_auth(), timeout=3)
            resp.raise_for_status()
            return resp.json().get('players', [])
        except Exception:
            return None

    def _write_event(self, event: dict):
        event = dict(event)
        event['ts'] = datetime.now().isoformat(timespec='seconds')
        os.makedirs(os.path.dirname(EVENT_LOG_FILE), exist_ok=True)
        if os.path.exists(EVENT_LOG_FILE) and os.path.getsize(EVENT_LOG_FILE) > MAX_EVENT_FILE_BYTES:
            rotated = EVENT_LOG_FILE + '.1'
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(EVENT_LOG_FILE, rotated)
        with open(EVENT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
```

`run.py` — `if __name__ == '__main__':` 블록 안, `serve(...)` 호출 직전에 추가 (프로덕션 엔트리에서만 기동해 테스트/디버그 이중 기동을 피한다):

```python
    # 팰월드 접속/퇴장 이벤트 폴러 (daemon thread)
    from service.palworld_service import PalworldService
    from service.palworld_event_poller import PalworldEventPoller
    PalworldEventPoller(PalworldService()).start()
    logger.info("Palworld event poller started (10s interval)")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_palworld_event_poller.py -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/service/palworld_event_poller.py suh-ai-server/flask/run.py suh-ai-server/flask/test/test_palworld_event_poller.py
git commit -m "팰월드 어드민 개편 : feat : REST 폴링 기반 접속/퇴장 이벤트 폴러 추가 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 5: Lucide 로컬 번들 + 공용 어드민 셸(base.html)

**Files:**
- Modify: `suh-ai-server/flask/frontend/package.json` (lucide 의존성 + copy 스크립트)
- Create: `suh-ai-server/flask/frontend/copy-vendor.js`
- Create: `suh-ai-server/flask/templates/admin/base.html`
- Modify: `suh-ai-server/flask/router/admin_router.py` (root/active 전달 + `/admin/logs` 라우트)
- Test: `suh-ai-server/flask/test/test_admin_router.py` (신규 — base.html 자체는 Task 8의 페이지 렌더 테스트로 검증되므로 여기선 라우트만)

**Interfaces:**
- Consumes: `static/js/admin-common.js` (apiFetch/showToast/escapeHtml — 기존 그대로)
- Produces:
  - `templates/admin/base.html` — Jinja 블록: `title`, `page_title`, `navbar_extra`, `navbar_actions`, `content`, `extra_js`. 컨텍스트 변수: `root`(`.`|`..`), `active`(`dashboard`|`palworld`|`flask-logs`)
  - `static/js/vendor/lucide.min.js` — 전역 `lucide.createIcons()` (base.html이 로드·호출)
  - 라우트: `GET /admin`, `GET /admin/palworld`, `GET /admin/logs`

- [ ] **Step 1: Lucide 설치 + 번들 복사 스크립트** — `frontend/copy-vendor.js` 신규:

```javascript
/* 빌드 시 벤더 JS를 static으로 복사 (CDN 의존 제거) */
const fs = require('fs');
const path = require('path');

const src = path.join(__dirname, 'node_modules', 'lucide', 'dist', 'umd', 'lucide.min.js');
const destDir = path.join(__dirname, '..', 'static', 'js', 'vendor');
fs.mkdirSync(destDir, { recursive: true });
fs.copyFileSync(src, path.join(destDir, 'lucide.min.js'));
console.log('copied: static/js/vendor/lucide.min.js');
```

`frontend/package.json`의 `scripts.build`를 다음으로 교체 (lucide 의존성은 Step 2의 `npm install lucide`가 추가한다 — 버전을 임의 고정하지 말 것):

```json
    "build": "tailwindcss -i input.css -o ../static/css/app.css --minify && node copy-vendor.js"
```

- [ ] **Step 2: 설치·빌드 실행 및 산출물 확인**

Run:
```bash
cd "D:\0-suh\project\suh-project-control\suh-ai-server\flask\frontend"
npm install
npm install lucide
npm run build
ls ../static/js/vendor/lucide.min.js
```
Expected: `lucide.min.js` 존재. npm install 실패 시 사내 미러 registry 설정 확인(`npm config get registry` → `http://npm.mirror.lab.somansa.com`)

- [ ] **Step 3: base.html 작성** — `templates/admin/base.html` 신규:

```html
<!DOCTYPE html>
<html lang="ko" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}SUH AI Server Admin{% endblock %}</title>
  <link rel="stylesheet" href="{{ root }}/static/css/app.css">
  <script>
    /* FOUC 방지 - CSS보다 먼저 저장된 테마 적용 */
    (function () {
      var saved = localStorage.getItem('suh_admin_theme');
      if (saved) document.documentElement.setAttribute('data-theme', saved);
    })();
  </script>
</head>
<body class="min-h-screen bg-base-200">

<div class="drawer lg:drawer-open">
  <input id="drawer-toggle" type="checkbox" class="drawer-toggle"/>

  <div class="drawer-content flex flex-col min-h-screen">
    <div class="navbar bg-base-100 shadow-sm sticky top-0 z-30">
      <div class="flex-none lg:hidden">
        <label for="drawer-toggle" class="btn btn-square btn-ghost" aria-label="메뉴 열기">
          <i data-lucide="menu" class="size-5"></i>
        </label>
      </div>
      <div class="flex-1 flex items-center">
        <h1 class="text-lg font-bold px-2">{% block page_title %}대시보드{% endblock %}</h1>
        {% block navbar_extra %}{% endblock %}
      </div>
      <div class="flex-none flex items-center gap-1 px-2">
        {% block navbar_actions %}{% endblock %}
        <label class="swap swap-rotate btn btn-ghost btn-circle" title="테마 전환">
          <input type="checkbox" id="theme-toggle"/>
          <i data-lucide="sun" class="swap-on size-5"></i>
          <i data-lucide="moon" class="swap-off size-5"></i>
        </label>
        <button class="btn btn-ghost btn-circle" onclick="resetApiKey()" title="API Key 변경">
          <i data-lucide="key-round" class="size-5"></i>
        </button>
      </div>
    </div>

    <main class="p-4 lg:p-6 flex-1">{% block content %}{% endblock %}</main>

    <footer class="footer footer-center p-4 bg-base-100 text-base-content border-t border-base-300">
      <aside><p>SUH AI Server Admin</p></aside>
    </footer>
  </div>

  <div class="drawer-side z-40">
    <label for="drawer-toggle" aria-label="사이드바 닫기" class="drawer-overlay"></label>
    <aside class="bg-base-100 min-h-full w-64 border-r border-base-300">
      <div class="flex items-center gap-3 px-4 py-5 border-b border-base-300">
        <i data-lucide="server" class="size-8 text-primary"></i>
        <span class="text-xl font-bold">SUH AI Server</span>
        <span class="badge badge-primary badge-sm">Admin</span>
      </div>
      <ul class="menu p-4 gap-1 w-full">
        <li>
          <a href="{{ root }}/admin" class="{{ 'menu-active' if active == 'dashboard' else '' }}">
            <i data-lucide="layout-dashboard" class="size-5"></i>대시보드
          </a>
        </li>
        <li>
          <a href="{{ root }}/admin/palworld" class="{{ 'menu-active' if active == 'palworld' else '' }}">
            <i data-lucide="gamepad-2" class="size-5"></i>팰월드 서버
          </a>
        </li>
        <li>
          <a href="{{ root }}/docs/swagger">
            <i data-lucide="file-code" class="size-5"></i>API 문서
          </a>
        </li>
        <li>
          <a href="{{ root }}/admin/logs" class="{{ 'menu-active' if active == 'flask-logs' else '' }}">
            <i data-lucide="scroll-text" class="size-5"></i>Flask 로그
          </a>
        </li>
      </ul>
    </aside>
  </div>
</div>

<dialog id="api-key-modal" class="modal">
  <div class="modal-box">
    <h3 class="font-bold text-lg flex items-center gap-2">
      <i data-lucide="key-round" class="size-5"></i>API Key 입력
    </h3>
    <p class="py-2 text-sm">nginx 인증용 X-API-Key를 입력하세요. 브라우저에 저장됩니다.</p>
    <input id="api-key-input" type="password" class="input input-bordered w-full" placeholder="API Key">
    <div class="modal-action">
      <button class="btn btn-primary" onclick="saveApiKey()">저장</button>
    </div>
  </div>
</dialog>
<div id="toast-container" class="toast toast-end z-50"></div>

<script src="{{ root }}/static/js/vendor/lucide.min.js"></script>
<script src="{{ root }}/static/js/admin-common.js"></script>
<script>
  lucide.createIcons();
  (function () {
    var toggle = document.getElementById('theme-toggle');
    toggle.checked = document.documentElement.getAttribute('data-theme') === 'light';
    toggle.addEventListener('change', function () {
      var theme = toggle.checked ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('suh_admin_theme', theme);
    });
  })();
</script>
{% block extra_js %}{% endblock %}
</body>
</html>
```

- [ ] **Step 4: admin_router 확장** — `router/admin_router.py` 전체 교체:

```python
"""
Admin pages router - DaisyUI 관리자 페이지 렌더링
root: 페이지 깊이에 따른 상대경로 프리픽스 (nginx 프리픽스 뒤에서도 동작)
"""
from flask import Blueprint, render_template

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin', methods=['GET'])
def dashboard():
    """관리 허브 대시보드"""
    return render_template('admin/dashboard.html', root='.', active='dashboard')


@admin_bp.route('/admin/palworld', methods=['GET'])
def palworld():
    """팰월드 서버 관리 페이지"""
    return render_template('admin/palworld.html', root='..', active='palworld')


@admin_bp.route('/admin/logs', methods=['GET'])
def flask_logs():
    """Flask 서버 로그 페이지"""
    return render_template('admin/logs.html', root='..', active='flask-logs')
```

주의: 이 시점에는 `admin/logs.html`이 아직 없고 dashboard/palworld는 구버전(독립 HTML)이라 `/admin`·`/admin/palworld`는 여전히 열리지만 `/admin/logs`는 500이다 — Task 8에서 해소된다. 이 Task의 커밋은 셸·라우트 준비 단계.

- [ ] **Step 5: Commit**

```bash
cd "D:\0-suh\project\suh-project-control"
git add suh-ai-server/flask/frontend/package.json suh-ai-server/flask/frontend/package-lock.json suh-ai-server/flask/frontend/copy-vendor.js suh-ai-server/flask/static/js/vendor/lucide.min.js suh-ai-server/flask/templates/admin/base.html suh-ai-server/flask/router/admin_router.py
git commit -m "팰월드 어드민 개편 : feat : Lucide 로컬 번들 및 daisyUI drawer 공용 셸 추가 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 6: 공용 로그 뷰어 (log-viewer.js)

**Files:**
- Create: `suh-ai-server/flask/static/js/log-viewer.js`

**Interfaces:**
- Consumes: 없음 (독립 모듈 — `window.lucide`는 있으면 사용)
- Produces (전역 함수, Task 7·8이 사용):
  - `createLogViewer(rootEl, config) -> {refresh: () => Promise<void>}`
    - `config.sources: [{id: string, label: string}]`
    - `config.fetchLogs(sourceId: string, lines: number) -> Promise<{logs: string[], exists?: boolean, log_file?: string, size_bytes?: number}>`
    - `config.formatLine?: (line: string, sourceId: string) => string`
  - `formatPalworldEvent(line: string) -> string` — Task 4 JSONL 한 줄을 한국어 문장으로

- [ ] **Step 1: 구현** — `static/js/log-viewer.js` 신규:

```javascript
/* 공용 로그 뷰어 — 팰월드 로그 탭 / Flask 로그 페이지에서 사용.
   소스 전환, 라인 수, 자동 새로고침(10초), Error/Warning 하이라이트,
   맨 아래일 때만 자동 스크롤, 파일 경로·크기 표시, 파일 없으면 경로 안내. */
function createLogViewer(rootEl, config) {
  var sources = config.sources;
  var currentSource = sources[0].id;
  var lines = 200;

  rootEl.innerHTML =
    '<div class="flex flex-wrap items-center gap-2 mb-3">' +
    '<div role="tablist" class="tabs tabs-box tabs-sm" data-role="sources"></div>' +
    '<select class="select select-sm w-28" data-role="lines">' +
    '<option value="100">100줄</option><option value="200" selected>200줄</option><option value="500">500줄</option>' +
    '</select>' +
    '<label class="label cursor-pointer gap-2 text-sm">' +
    '<input type="checkbox" class="toggle toggle-sm toggle-primary" data-role="auto" checked><span>자동 새로고침</span>' +
    '</label>' +
    '<button type="button" class="btn btn-ghost btn-sm" data-role="refresh">' +
    '<i data-lucide="refresh-cw" class="size-4"></i>새로고침</button>' +
    '</div>' +
    '<div class="text-xs opacity-60 mb-2 font-mono break-all" data-role="meta"></div>' +
    '<pre class="bg-base-300 rounded-box text-xs leading-5 overflow-auto max-h-[28rem] p-4" data-role="view">불러오는 중…</pre>';

  var sourcesEl = rootEl.querySelector('[data-role="sources"]');
  var viewEl = rootEl.querySelector('[data-role="view"]');
  var metaEl = rootEl.querySelector('[data-role="meta"]');

  sources.forEach(function (s) {
    var tab = document.createElement('button');
    tab.type = 'button';
    tab.setAttribute('role', 'tab');
    tab.className = 'tab' + (s.id === currentSource ? ' tab-active' : '');
    tab.textContent = s.label;
    tab.addEventListener('click', function () {
      currentSource = s.id;
      sourcesEl.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('tab-active'); });
      tab.classList.add('tab-active');
      refresh();
    });
    sourcesEl.appendChild(tab);
  });
  if (sources.length < 2) sourcesEl.classList.add('hidden');

  rootEl.querySelector('[data-role="lines"]').addEventListener('change', function (e) {
    lines = parseInt(e.target.value, 10);
    refresh();
  });
  rootEl.querySelector('[data-role="refresh"]').addEventListener('click', function () { refresh(); });

  function levelClass(line) {
    if (/error|fatal|fail/i.test(line)) return 'text-error';
    if (/warn/i.test(line)) return 'text-warning';
    return '';
  }

  async function refresh() {
    var data;
    try {
      data = await config.fetchLogs(currentSource, lines);
    } catch (e) { return; /* 401은 apiFetch가 modal 처리 */ }
    var atBottom = viewEl.scrollHeight - viewEl.scrollTop - viewEl.clientHeight < 40;
    if (data.exists === false) {
      metaEl.textContent = '';
      viewEl.textContent = '로그 파일이 아직 없습니다: ' + (data.log_file || '(경로 미상)');
      return;
    }
    metaEl.textContent = data.log_file
      ? data.log_file + ' (' + ((data.size_bytes || 0) / 1024 / 1024).toFixed(1) + ' MB)'
      : '';
    var logs = data.logs || [];
    viewEl.textContent = '';
    if (!logs.length) {
      viewEl.textContent = '(로그 없음)';
      return;
    }
    logs.forEach(function (line) {
      var span = document.createElement('span');
      var text = config.formatLine ? config.formatLine(line, currentSource) : line;
      span.textContent = text + '\n';
      var cls = levelClass(text);
      if (cls) span.className = cls;
      viewEl.appendChild(span);
    });
    if (atBottom) viewEl.scrollTop = viewEl.scrollHeight;
  }

  setInterval(function () {
    if (rootEl.querySelector('[data-role="auto"]').checked && !document.hidden) refresh();
  }, 10000);

  refresh();
  if (window.lucide) lucide.createIcons();
  return { refresh: refresh };
}

/* 팰월드 이벤트 JSONL 한 줄 → 한국어 문장 (파싱 실패 시 원문 그대로) */
function formatPalworldEvent(line) {
  try {
    var e = JSON.parse(line);
    if (e.type === 'join' || e.type === 'leave') {
      var name = (e.player && e.player.name) || '?';
      var verb = e.type === 'join' ? '접속' : '퇴장';
      return '[' + e.ts + "] '" + name + "' " + verb + ' (현재 ' + e.count + '명)';
    }
    if (e.type === 'server_up') return '[' + e.ts + '] 서버가 시작되었습니다';
    if (e.type === 'server_down') return '[' + e.ts + '] 서버가 중지되었습니다';
    return line;
  } catch (err) {
    return line;
  }
}
```

- [ ] **Step 2: Commit** (브라우저 동작 검증은 Task 8 Step 6에서 페이지와 함께)

```bash
git add suh-ai-server/flask/static/js/log-viewer.js
git commit -m "팰월드 어드민 개편 : feat : 공용 로그 뷰어 모듈 추가 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 7: 팰월드 페이지 재작성 (히어로 + 접속 가이드 + 탭)

**Files:**
- Modify: `suh-ai-server/flask/templates/admin/palworld.html` (전체 교체)
- Modify: `suh-ai-server/flask/static/js/palworld.js` (일부 함수 교체·추가)

**Interfaces:**
- Consumes: `base.html` 블록(Task 5), `createLogViewer`/`formatPalworldEvent`(Task 6), `GET /palworld/guide`(Task 3), `GET /palworld/logs?source=`(Task 2), 기존 `/palworld/status|start|stop|restart|settings|backups`
- Produces: 없음 (말단 페이지)

- [ ] **Step 1: palworld.html 전체 교체**:

```html
{% extends "admin/base.html" %}
{% block title %}팰월드 서버 관리 | SUH AI Server{% endblock %}
{% block page_title %}팰월드 서버{% endblock %}
{% block navbar_extra %}
<span id="state-badge" class="badge badge-ghost ml-2">확인중</span>
{% endblock %}
{% block content %}
<div class="space-y-6 max-w-5xl mx-auto">

  <div class="card bg-base-100 shadow">
    <div class="card-body gap-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="card-title text-base">
          <i data-lucide="activity" class="size-5"></i>서버 상태
        </h2>
        <div class="flex gap-2">
          <button id="btn-start" class="btn btn-success btn-sm" onclick="controlServer('start')">
            <i data-lucide="play" class="size-4"></i>시작
          </button>
          <button id="btn-stop" class="btn btn-error btn-sm" onclick="controlServer('stop')">
            <i data-lucide="square" class="size-4"></i>중지
          </button>
          <button id="btn-restart" class="btn btn-warning btn-sm" onclick="controlServer('restart')">
            <i data-lucide="rotate-cw" class="size-4"></i>재시작
          </button>
        </div>
      </div>
      <div class="stats stats-vertical sm:stats-horizontal w-full bg-base-200">
        <div class="stat">
          <div class="stat-figure text-primary"><i data-lucide="users" class="size-6"></i></div>
          <div class="stat-title">접속자</div>
          <div id="stat-players" class="stat-value text-2xl">-</div>
          <div id="stat-maxplayers" class="stat-desc">/ - 명</div>
        </div>
        <div class="stat">
          <div class="stat-figure text-primary"><i data-lucide="gauge" class="size-6"></i></div>
          <div class="stat-title">서버 FPS</div>
          <div id="stat-fps" class="stat-value text-2xl">-</div>
        </div>
        <div class="stat">
          <div class="stat-figure text-primary"><i data-lucide="clock" class="size-6"></i></div>
          <div class="stat-title">업타임</div>
          <div id="stat-uptime" class="stat-value text-2xl">-</div>
        </div>
      </div>
    </div>
  </div>

  <div class="card bg-base-100 shadow border border-primary/30">
    <div class="card-body">
      <h2 class="card-title text-base">
        <i data-lucide="map" class="size-5"></i>게임 접속 방법
      </h2>
      <ul class="steps steps-vertical sm:steps-horizontal w-full my-2 text-sm">
        <li class="step step-primary">타이틀 → 멀티플레이<br>참가하기 (전용서버)</li>
        <li class="step step-primary">"비밀번호를 입력해주세요"<br>체크</li>
        <li class="step step-primary">아래 주소·비밀번호 입력</li>
      </ul>
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="bg-base-200 rounded-box p-4">
          <div class="text-xs opacity-60 mb-1">서버 주소</div>
          <div class="flex items-center justify-between gap-2">
            <code id="guide-address" class="font-mono text-sm break-all">불러오는 중…</code>
            <button type="button" class="btn btn-ghost btn-xs" onclick="copyGuide('guide-address', '서버 주소')" title="복사">
              <i data-lucide="copy" class="size-4"></i>
            </button>
          </div>
        </div>
        <div class="bg-base-200 rounded-box p-4">
          <div class="text-xs opacity-60 mb-1">접속 비밀번호</div>
          <div class="flex items-center justify-between gap-2">
            <code id="guide-password" class="font-mono text-sm">불러오는 중…</code>
            <button type="button" id="guide-password-copy" class="btn btn-ghost btn-xs" onclick="copyGuide('guide-password', '비밀번호')" title="복사">
              <i data-lucide="copy" class="size-4"></i>
            </button>
          </div>
        </div>
      </div>
      <p id="guide-server-info" class="text-sm opacity-70 mt-1"></p>
    </div>
  </div>

  <div role="tablist" class="tabs tabs-lift">
    <input type="radio" name="main_tabs" role="tab" class="tab" aria-label="설정" checked>
    <div role="tabpanel" class="tab-content bg-base-100 border-base-300 rounded-box p-6">
      <div class="alert alert-warning mb-4 text-sm">
        <i data-lucide="triangle-alert" class="size-5"></i>
        <span>설정은 서버를 <b>완전히 중지한 뒤</b> 저장해야 합니다. 실행 중 수정하면 종료 시 기존 값으로 덮어써집니다.</span>
      </div>
      <div class="settings-toolbar">
        <div>
          <h2 class="settings-title">서버 기본 설정</h2>
          <p class="settings-subtitle">현재 저장값을 보여줍니다. 추천값은 버튼으로 한 번에 적용할 수 있습니다.</p>
        </div>
        <button type="button" class="btn btn-outline btn-sm" onclick="applyRecommendedSettings()">추천값 적용</button>
      </div>
      <div class="settings-head" aria-hidden="true">
        <span>항목</span><span>현재값</span><span>기본값 / 추천값</span><span>설명</span>
      </div>
      <div id="settings-form" class="settings-list"></div>
      <div class="settings-actions">
        <button class="btn btn-primary" onclick="saveSettings()">저장</button>
        <button class="btn btn-secondary" onclick="stopSaveRestart()">중지 → 저장 → 재시작</button>
      </div>
    </div>

    <input type="radio" name="main_tabs" role="tab" class="tab" aria-label="로그">
    <div role="tabpanel" class="tab-content bg-base-100 border-base-300 rounded-box p-6">
      <div id="palworld-log-viewer"></div>
    </div>

    <input type="radio" name="main_tabs" role="tab" class="tab" aria-label="백업">
    <div role="tabpanel" class="tab-content bg-base-100 border-base-300 rounded-box p-6">
      <button class="btn btn-primary mb-4" onclick="createBackup()">
        <i data-lucide="archive" class="size-4"></i>지금 백업
      </button>
      <div class="overflow-x-auto">
        <table class="table table-zebra">
          <thead><tr><th>이름</th><th>크기(MB)</th><th>생성 시각</th></tr></thead>
          <tbody id="backup-list"></tbody>
        </table>
      </div>
    </div>

    <input type="radio" name="main_tabs" role="tab" class="tab" aria-label="플레이어">
    <div role="tabpanel" class="tab-content bg-base-100 border-base-300 rounded-box p-6">
      <div class="overflow-x-auto">
        <table class="table table-sm">
          <thead><tr><th>이름</th><th>레벨</th><th>Ping</th></tr></thead>
          <tbody id="player-list"><tr><td colspan="3">-</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<dialog id="confirm-modal" class="modal">
  <div class="modal-box">
    <h3 class="font-bold text-lg flex items-center gap-2">
      <i data-lucide="circle-help" class="size-5"></i>확인
    </h3>
    <p id="confirm-message" class="py-3 text-sm"></p>
    <div class="modal-action">
      <form method="dialog" class="flex gap-2">
        <button class="btn btn-ghost">취소</button>
        <button class="btn btn-primary" value="ok">확인</button>
      </form>
    </div>
  </div>
  <form method="dialog" class="modal-backdrop"><button aria-label="닫기">close</button></form>
</dialog>
{% endblock %}
{% block extra_js %}
<script src="{{ root }}/static/js/log-viewer.js"></script>
<script src="{{ root }}/static/js/palworld.js"></script>
{% endblock %}
```

- [ ] **Step 2: palworld.js 수정** — 아래 3가지 변경:

**(a)** `refreshLogs` 함수(215-223라인)를 삭제하고, 그 자리에 confirm modal + 가이드 + 뷰어 초기화 추가:

```javascript
/* 브라우저 confirm() 대체 — daisyUI modal, ok 버튼 value="ok" */
function confirmAction(message) {
  return new Promise(function (resolve) {
    var modal = document.getElementById('confirm-modal');
    document.getElementById('confirm-message').textContent = message;
    modal.returnValue = '';
    function onClose() {
      modal.removeEventListener('close', onClose);
      resolve(modal.returnValue === 'ok');
    }
    modal.addEventListener('close', onClose);
    modal.showModal();
  });
}

async function loadGuide() {
  try {
    const resp = await apiFetch(API + '/guide');
    const data = await resp.json();
    document.getElementById('guide-address').textContent = data.address;
    const passwordEl = document.getElementById('guide-password');
    if (data.has_password) {
      passwordEl.textContent = data.password;
    } else {
      passwordEl.textContent = '없음 (공개 서버)';
      document.getElementById('guide-password-copy').classList.add('hidden');
    }
    const parts = [];
    if (data.server_name) parts.push('서버 이름: ' + data.server_name);
    if (data.max_players) parts.push('최대 ' + data.max_players + '명');
    document.getElementById('guide-server-info').textContent = parts.join(' · ');
  } catch (e) { /* 401은 modal 처리 */ }
}

async function copyGuide(elementId, label) {
  const text = document.getElementById(elementId).textContent;
  try {
    await navigator.clipboard.writeText(text);
    showToast(label + ' 복사됨: ' + escapeHtml(text), 'success');
  } catch (e) {
    showToast('복사 실패 - 직접 선택해서 복사해주세요', 'error');
  }
}

function initLogViewer() {
  createLogViewer(document.getElementById('palworld-log-viewer'), {
    sources: [
      { id: 'events', label: '이벤트' },
      { id: 'game', label: '게임 로그' },
      { id: 'stdout', label: 'stdout' },
      { id: 'stderr', label: 'stderr' },
    ],
    fetchLogs: async function (source, lines) {
      const resp = await apiFetch(API + '/logs?source=' + source + '&lines=' + lines);
      return resp.json();
    },
    formatLine: function (line, source) {
      return source === 'events' ? formatPalworldEvent(line) : line;
    },
  });
}
```

**(b)** `controlServer`(77-88라인)와 `stopSaveRestart`(197-213라인)의 첫 줄 `if (!confirm(...)) return;`을 async/await 형태로 교체:

```javascript
async function controlServer(action) {
  const labels = { start: '시작', stop: '중지', restart: '재시작' };
  if (!(await confirmAction('서버를 ' + labels[action] + ' 하시겠습니까?'))) return;
  try {
    const resp = await apiFetch(API + '/' + action, { method: 'POST' });
    const data = await resp.json();
    if (data.success) showToast(labels[action] + ' 완료', 'success');
    else showToast(data.error || labels[action] + ' 실패', 'error');
  } catch (e) {
    showToast(String(e), 'error');
  }
  setTimeout(refreshStatus, 2000);
}
```

`stopSaveRestart`의 첫 줄만 교체:

```javascript
async function stopSaveRestart() {
  if (!(await confirmAction('서버를 중지하고 설정 저장 후 재시작합니다. 진행할까요?'))) return;
  // ...이하 기존 코드 유지 (await apiFetch(API + '/stop' ...)
```

**(c)** 파일 끝 `DOMContentLoaded` 블록을 교체 (`refreshLogs` 참조 제거):

```javascript
document.addEventListener('DOMContentLoaded', function () {
  refreshStatus();
  loadSettings();
  loadGuide();
  loadBackups();
  initLogViewer();
  setInterval(refreshStatus, 5000);
});
```

- [ ] **Step 3: 커밋**

```bash
git add suh-ai-server/flask/templates/admin/palworld.html suh-ai-server/flask/static/js/palworld.js
git commit -m "팰월드 어드민 개편 : feat : 팰월드 페이지 셸 이식 및 접속 가이드/로그 뷰어 탑재 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 8: 대시보드 재작성 + Flask 로그 페이지 + /health + 렌더 테스트

**Files:**
- Modify: `suh-ai-server/flask/templates/admin/dashboard.html` (전체 교체)
- Create: `suh-ai-server/flask/templates/admin/logs.html`
- Modify: `suh-ai-server/flask/app.py` (`/health` 추가)
- Test: `suh-ai-server/flask/test/test_admin_router.py` (신규)

**Interfaces:**
- Consumes: `base.html`(Task 5), `createLogViewer`(Task 6), `GET /logs`(기존 log_router), `GET /palworld/status`(기존)
- Produces: `GET /health` → 200 `{"status": "ok"}` (deploy-flask.ps1의 health check가 이 엔드포인트를 기대함)

- [ ] **Step 1: 실패하는 렌더 테스트 작성** — `test/test_admin_router.py` 신규:

```python
"""test_admin_router.py — 어드민 페이지 렌더 및 no-emoji 검증"""
import os
import re
import pytest
from flask import Flask

EMOJI_RE = re.compile('[\U0001F300-\U0001FAFF☀-➿]')


@pytest.fixture
def client():
    from router.admin_router import admin_bp
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
    app = Flask(__name__, template_folder=template_dir)
    app.register_blueprint(admin_bp)
    return app.test_client()


def test_dashboard_renders_with_shell(client):
    resp = client.get('/admin')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '대시보드' in body
    assert 'drawer' in body
    assert 'data-lucide' in body


def test_palworld_page_renders_guide_and_tabs(client):
    resp = client.get('/admin/palworld')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '게임 접속 방법' in body
    assert 'palworld-log-viewer' in body
    assert 'confirm-modal' in body


def test_flask_logs_page_renders(client):
    resp = client.get('/admin/logs')
    assert resp.status_code == 200
    assert 'Flask 서버 로그' in resp.get_data(as_text=True)


def test_no_emoji_icons_on_any_admin_page(client):
    for path in ('/admin', '/admin/palworld', '/admin/logs'):
        body = client.get(path).get_data(as_text=True)
        match = EMOJI_RE.search(body)
        assert not match, f'{path} 에 이모지가 남아있음: {match.group() if match else ""}'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest test/test_admin_router.py -v`
Expected: FAIL — dashboard는 구버전(이모지 잔존, drawer 없음), `/admin/logs`는 TemplateNotFound

- [ ] **Step 3: dashboard.html 전체 교체**:

```html
{% extends "admin/base.html" %}
{% block title %}SUH AI Server Admin{% endblock %}
{% block page_title %}대시보드{% endblock %}
{% block content %}
<div class="space-y-6 max-w-5xl mx-auto">

  <div class="stats stats-vertical sm:stats-horizontal shadow w-full bg-base-100">
    <div class="stat">
      <div class="stat-figure text-primary"><i data-lucide="server" class="size-6"></i></div>
      <div class="stat-title">Flask 서버</div>
      <div id="stat-flask" class="stat-value text-2xl">확인중</div>
      <div class="stat-desc">OCR · Vision · 관리 API</div>
    </div>
    <div class="stat">
      <div class="stat-figure text-primary"><i data-lucide="gamepad-2" class="size-6"></i></div>
      <div class="stat-title">팰월드 서버</div>
      <div id="stat-palworld" class="stat-value text-2xl">확인중</div>
      <div id="stat-palworld-desc" class="stat-desc">-</div>
    </div>
    <div class="stat">
      <div class="stat-figure text-primary"><i data-lucide="users" class="size-6"></i></div>
      <div class="stat-title">팰월드 접속자</div>
      <div id="stat-players" class="stat-value text-2xl">-</div>
      <div id="stat-players-desc" class="stat-desc">/ - 명</div>
    </div>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
    <a href="./admin/palworld" class="card bg-base-100 shadow-md hover:shadow-xl transition-shadow">
      <div class="card-body">
        <h2 class="card-title text-base">
          <i data-lucide="gamepad-2" class="size-5 text-primary"></i>팰월드 서버 관리
          <span id="pal-badge" class="badge badge-ghost badge-sm">확인중</span>
        </h2>
        <p class="text-sm opacity-70">서버 제어 · 접속 가이드 · 설정 · 로그 · 백업</p>
      </div>
    </a>
    <a href="./docs/swagger" class="card bg-base-100 shadow-md hover:shadow-xl transition-shadow">
      <div class="card-body">
        <h2 class="card-title text-base">
          <i data-lucide="file-code" class="size-5 text-primary"></i>API 문서
        </h2>
        <p class="text-sm opacity-70">OCR · Vision API Swagger 문서</p>
      </div>
    </a>
    <a href="./admin/logs" class="card bg-base-100 shadow-md hover:shadow-xl transition-shadow">
      <div class="card-body">
        <h2 class="card-title text-base">
          <i data-lucide="scroll-text" class="size-5 text-primary"></i>Flask 로그
        </h2>
        <p class="text-sm opacity-70">Flask 서버 로그 조회 (레벨 필터 · 검색)</p>
      </div>
    </a>
  </div>
</div>
{% endblock %}
{% block extra_js %}
<script>
  document.addEventListener('DOMContentLoaded', async function () {
    try {
      const resp = await apiFetch('./health');
      document.getElementById('stat-flask').textContent = resp.ok ? '온라인' : '오류';
    } catch (e) {
      document.getElementById('stat-flask').textContent = '오류';
    }
    try {
      const resp = await apiFetch('./palworld/status');
      const data = await resp.json();
      const running = data.state === 'running';
      document.getElementById('stat-palworld').textContent = running ? '온라인' : '중지됨';
      document.getElementById('stat-palworld-desc').textContent = data.state.toUpperCase();
      const badge = document.getElementById('pal-badge');
      badge.textContent = data.state.toUpperCase();
      badge.className = 'badge badge-sm ' + (running ? 'badge-success' : 'badge-error');
      if (data.rest_available && data.metrics) {
        document.getElementById('stat-players').textContent = data.metrics.currentplayernum;
        document.getElementById('stat-players-desc').textContent = '/ ' + data.metrics.maxplayernum + ' 명';
      }
    } catch (e) { /* 401 modal은 apiFetch가 처리 */ }
  });
</script>
{% endblock %}
```

- [ ] **Step 4: logs.html 신규 + /health 추가** — `templates/admin/logs.html`:

```html
{% extends "admin/base.html" %}
{% block title %}Flask 로그 | SUH AI Server{% endblock %}
{% block page_title %}Flask 서버 로그{% endblock %}
{% block content %}
<div class="card bg-base-100 shadow max-w-5xl mx-auto">
  <div class="card-body">
    <h2 class="card-title text-base">
      <i data-lucide="scroll-text" class="size-5"></i>Flask 서버 로그
    </h2>
    <div class="flex flex-wrap gap-2 mb-2">
      <select id="log-level" class="select select-sm w-36">
        <option value="">전체 레벨</option>
        <option value="ERROR">ERROR</option>
        <option value="WARNING">WARNING</option>
        <option value="INFO">INFO</option>
      </select>
      <input id="log-search" class="input input-sm w-56" placeholder="검색어 입력 후 Enter">
    </div>
    <div id="flask-log-viewer"></div>
  </div>
</div>
{% endblock %}
{% block extra_js %}
<script src="{{ root }}/static/js/log-viewer.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', function () {
    const viewer = createLogViewer(document.getElementById('flask-log-viewer'), {
      sources: [{ id: 'flask', label: 'nssm-stderr.log' }],
      fetchLogs: async function (source, lines) {
        const level = document.getElementById('log-level').value;
        const search = document.getElementById('log-search').value.trim();
        let url = '../logs?lines=' + lines;
        if (level) url += '&level=' + encodeURIComponent(level);
        if (search) url += '&search=' + encodeURIComponent(search);
        const resp = await apiFetch(url);
        const data = await resp.json();
        if (resp.status === 404) return { logs: [], exists: false, log_file: data.log_file };
        return { logs: data.logs || [], exists: true, log_file: data.log_file };
      },
    });
    document.getElementById('log-level').addEventListener('change', function () { viewer.refresh(); });
    document.getElementById('log-search').addEventListener('change', function () { viewer.refresh(); });
  });
</script>
{% endblock %}
```

`app.py` — `@app.errorhandler(404)` 앞에 추가 (deploy-flask.ps1이 `http://localhost:5000/health`를 체크하는데 지금까지 엔드포인트가 없어 항상 WARN이었다):

```python
@app.route('/health', methods=['GET'])
def health():
    """헬스체크 (deploy 스크립트·대시보드가 사용)"""
    return jsonify({'status': 'ok'}), 200
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest test -v`
Expected: 전부 PASS (no-emoji 테스트 포함 — 실패하면 남은 이모지를 Lucide로 교체)

- [ ] **Step 6: CSS 재빌드 + 브라우저 스모크 테스트**

```bash
cd "D:\0-suh\project\suh-project-control\suh-ai-server\flask\frontend"
npm run build
cd ..
python app.py
```

브라우저에서 `http://localhost:5000/admin` 확인 (API Key modal은 값 아무거나 — 로컬은 nginx 없음):
- [ ] 사이드바 4메뉴 + Lucide 아이콘 렌더, 창 좁히면 햄버거 드로어
- [ ] 테마 토글 동작 + 새로고침 후 유지
- [ ] `/admin/palworld`: 가이드 카드에 주소 표시(ini 없는 로컬은 주소만), 복사 버튼 toast, 로그 탭 소스 4개 전환(파일 없으면 경로 안내 문구), 제어 버튼 → daisyUI modal
- [ ] `/admin/logs`: 뷰어 렌더 (로컬은 nssm-stderr.log 없음 → 안내 문구)

확인 후 서버 종료(Ctrl+C).

- [ ] **Step 7: Commit**

```bash
git add suh-ai-server/flask/templates/admin/dashboard.html suh-ai-server/flask/templates/admin/logs.html suh-ai-server/flask/app.py suh-ai-server/flask/test/test_admin_router.py suh-ai-server/flask/static/css/app.css
git commit -m "팰월드 어드민 개편 : feat : 대시보드 재설계 및 Flask 로그 페이지, /health 추가 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

### Task 9: NSSM 로그 로테이션 + 최종 검증

**Files:**
- Modify: `suh-ai-server/scripts/setup-palworld.ps1:104-109`

**Interfaces:**
- Consumes: 없음
- Produces: 배포 서버에서 스크립트 재실행 시 NSSM 로테이션 적용

- [ ] **Step 1: setup-palworld.ps1 수정** — `& nssm set $serviceName AppStopMethodConsole 15000` 라인 뒤에 추가:

```powershell
# 로그 로테이션: stdout/stderr가 10MB 넘으면 회전 (무한 성장 방지)
& nssm set $serviceName AppRotateFiles 1
& nssm set $serviceName AppRotateOnline 1
& nssm set $serviceName AppRotateBytes 10485760
```

- [ ] **Step 2: 전체 테스트 + 빌드 최종 확인**

```bash
cd "D:\0-suh\project\suh-project-control\suh-ai-server\flask"
python -m pytest test -v
cd frontend && npm run build
```

Expected: 테스트 전부 PASS, 빌드 성공

- [ ] **Step 3: Commit**

```bash
cd "D:\0-suh\project\suh-project-control"
git add suh-ai-server/scripts/setup-palworld.ps1
git commit -m "팰월드 어드민 개편 : chore : NSSM 로그 로테이션 설정 추가 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

- [ ] **Step 4: 스펙·플랜 문서 커밋**

```bash
git add docs/superpowers/specs/2026-07-14-palworld-admin-overhaul-design.md docs/superpowers/plans/2026-07-14-palworld-admin-overhaul.md .issue/palworld-admin-overhaul.md
git commit -m "팰월드 어드민 개편 : docs : 설계 스펙 및 구현 계획 문서 추가 https://github.com/Cassiiopeia/suh-project-control/issues/53"
```

---

## 배포 메모 (구현 완료 후 사용자 안내용 — 코드 아님)

1. 서버에서 `setup-palworld.ps1` 1회 재실행 (관리자 PowerShell) → NSSM 로테이션 적용
2. Flask 재배포 시 `frontend`의 `npm install && npm run build` 산출물(`static/css/app.css`, `static/js/vendor/lucide.min.js`)이 함께 배포되는지 확인 (git에 커밋되므로 기본 포함)
3. 이벤트 로그는 배포 후 폴러가 돌기 시작해야 쌓인다 — 첫 접속/퇴장 발생 전까지 이벤트 탭은 "(로그 없음)" 또는 파일 경로 안내가 정상
