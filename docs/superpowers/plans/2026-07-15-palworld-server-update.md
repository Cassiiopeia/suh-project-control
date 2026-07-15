# 팰월드 서버 바이너리 업데이트 구현 계획 (#73)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** SteamCMD 기반 서버 바이너리 업데이트(수동 버튼 + 자동 감지·자동 실행)를 어드민에 추가한다.

**Architecture:** 신규 `service/palworld_updater.py` 모듈(전역 상태 + 백그라운드 스레드)이 감지·실행을 담당, 라우터 3개 엔드포인트, UI는 서버 상태 카드에 배지/버튼/진행 패널.

**Tech Stack:** Flask, threading, subprocess(SteamCMD), daisyUI 5 + Tailwind 4(로컬 빌드), pytest

## Global Constraints

- 커밋 메시지: `팰월드 서버 업데이트 : <type> : <설명> https://github.com/Cassiiopeia/suh-project-control/issues/73` (AI 흔적 trailer 절대 금지)
- 감사 기록은 `audit_service.record()` 재사용 — fail-open이므로 업데이트 흐름을 절대 막지 않는다
- steamcmd 실패 시에도 PalServer 서비스를 반드시 재시작 시도한다 (서버 방치 금지)
- 백업 실패는 경고만 하고 업데이트를 계속한다
- 템플릿/JS 변경 후 CSS 재빌드 필수: `cd suh-ai-server/flask/frontend && npm run build` 후 신규 daisyUI 클래스가 `../static/css/app.css`에 있는지 grep 검증
- 전체 테스트: `cd suh-ai-server/flask && python -m pytest -q` — 기존 99개 회귀 없음

---

### Task 1: 백엔드 — updater 모듈 + 라우터 + 감사 액션

**Files:**
- Modify: `suh-ai-server/flask/config/palworld_config.py` (상수 추가)
- Create: `suh-ai-server/flask/service/palworld_updater.py`
- Modify: `suh-ai-server/flask/service/audit_service.py` (`SERVER_UPDATE` enum 한 줄)
- Modify: `suh-ai-server/flask/router/palworld_router.py` (엔드포인트 3개)
- Modify: `suh-ai-server/flask/router/palworld_swagger.py` (기존 패턴대로 3개 문서화)
- Modify: `suh-ai-server/flask/run.py` (auto_check_loop 데몬 스레드 — 기존 이벤트 폴러 시작 블록과 동일 위치·패턴)
- Test: `suh-ai-server/flask/test/test_palworld_updater.py` (신규), `test_palworld_router.py` (추가)

**Interfaces:**
- Produces: `palworld_updater.check_for_update() -> dict`, `start_update(trigger, actor_ip) -> bool`, `get_state() -> dict`, `auto_check_loop(interval_sec)`
- `get_state()` 반환: `{status, step, trigger, error, started_at, finished_at, local_build, remote_build, update_available, checked_at, log: [str]}`

**Step 1: palworld_config.py 상수 추가** (기존 상수들 아래)

```python
# 서버 바이너리 업데이트 (SteamCMD)
STEAMCMD_EXE = os.path.join(PALWORLD_BASE_DIR, "steamcmd", "steamcmd.exe")
PALWORLD_APP_ID = "2394010"
APP_MANIFEST_PATH = os.path.join(PALWORLD_BASE_DIR, "steamcmd", "steamapps",
                                 f"appmanifest_{PALWORLD_APP_ID}.acf")
UPDATE_CHECK_INTERVAL_SEC = 1800   # 새 빌드 자동 감지 주기 (30분)
UPDATE_LOG_MAXLEN = 300            # 업데이트 진행 로그 링버퍼
```

**Step 2: audit_service.py — enum 추가**

`AuditAction`에 `SERVER_UPDATE = "SERVER_UPDATE"` 한 줄 추가 (BACKUP_CREATE 아래).

**Step 3: RED — test_palworld_updater.py 작성** (아래 전체 코드, 실행해 실패 확인)

```python
"""palworld_updater 단위 테스트 — subprocess/서비스는 전부 mock"""
import sys
import os
import time
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from service import palworld_updater as updater


APP_INFO_FIXTURE = '''
"2394010"
{
    "common" { "name" "Palworld Dedicated Server" }
    "depots"
    {
        "branches"
        {
            "public"
            {
                "buildid"   "20250701"
                "timeupdated"   "1751900000"
            }
            "beta" { "buildid" "99999999" }
        }
    }
}
'''


@pytest.fixture(autouse=True)
def reset_state():
    with updater._lock:
        updater._state.update({'status': 'idle', 'step': None, 'trigger': None,
                               'error': None, 'started_at': None, 'finished_at': None})
    updater._log.clear()
    updater._version.update({'local_build': None, 'remote_build': None,
                             'update_available': None, 'checked_at': None})
    yield


def test_parse_remote_buildid_public_branch():
    assert updater.parse_remote_buildid(APP_INFO_FIXTURE) == '20250701'


def test_parse_remote_buildid_missing_returns_none():
    assert updater.parse_remote_buildid('no vdf here') is None


def test_get_local_buildid_from_acf(tmp_path):
    acf = tmp_path / 'appmanifest_2394010.acf'
    acf.write_text('"AppState"\n{\n\t"appid"\t\t"2394010"\n\t"buildid"\t\t"20250601"\n}\n', encoding='utf-8')
    with patch.object(updater, 'APP_MANIFEST_PATH', str(acf)):
        assert updater.get_local_buildid() == '20250601'


def test_get_local_buildid_missing_file_returns_none():
    with patch.object(updater, 'APP_MANIFEST_PATH', r'C:\nonexistent\x.acf'):
        assert updater.get_local_buildid() is None


def test_check_for_update_detects_new_build():
    with patch.object(updater, 'get_local_buildid', return_value='100'), \
         patch.object(updater, 'get_remote_buildid', return_value='200'):
        info = updater.check_for_update()
    assert info['update_available'] is True
    assert info['local_build'] == '100' and info['remote_build'] == '200'


def test_check_for_update_same_build_not_available():
    with patch.object(updater, 'get_local_buildid', return_value='100'), \
         patch.object(updater, 'get_remote_buildid', return_value='100'):
        assert updater.check_for_update()['update_available'] is False


def test_check_for_update_unknown_when_remote_missing():
    with patch.object(updater, 'get_local_buildid', return_value='100'), \
         patch.object(updater, 'get_remote_buildid', return_value=None):
        assert updater.check_for_update()['update_available'] is None


def test_start_update_guards_double_run():
    with updater._lock:
        updater._state['status'] = 'running'
    assert updater.start_update('manual', '1.2.3.4') is False


def test_start_update_records_audit_and_spawns_thread():
    with patch.object(updater.audit_service, 'record') as mock_record, \
         patch.object(updater.threading, 'Thread') as mock_thread:
        assert updater.start_update('manual', '1.2.3.4') is True
    args = mock_record.call_args[0]
    assert args[1] == updater.AuditAction.SERVER_UPDATE
    assert args[2] == '1.2.3.4'
    assert mock_record.call_args[0][3]['trigger'] == 'manual'
    mock_thread.assert_called_once()
    assert updater._state['status'] == 'running'


def _mock_service(state='running'):
    service = MagicMock()
    service.get_service_state.return_value = state
    service.create_backup.return_value = {'name': 'backup_x'}
    return service


def test_run_update_happy_path_order():
    service = _mock_service()
    calls = []
    service.create_backup.side_effect = lambda: calls.append('backup') or {'name': 'b'}
    service.stop.side_effect = lambda: calls.append('stop')
    service.start.side_effect = lambda: calls.append('start')
    with patch.object(updater, 'PalworldService', create=True), \
         patch('service.palworld_service.PalworldService', return_value=service), \
         patch.object(updater, '_run_steamcmd_update', side_effect=lambda: calls.append('steamcmd')), \
         patch.object(updater, 'get_local_buildid', return_value='200'):
        updater._run_update()
    assert calls == ['backup', 'stop', 'steamcmd', 'start']
    assert updater._state['status'] == 'done'


def test_run_update_backup_failure_continues():
    service = _mock_service()
    service.create_backup.side_effect = RuntimeError('disk full')
    with patch('service.palworld_service.PalworldService', return_value=service), \
         patch.object(updater, '_run_steamcmd_update'), \
         patch.object(updater, 'get_local_buildid', return_value='200'):
        updater._run_update()
    assert updater._state['status'] == 'done'
    service.start.assert_called()


def test_run_update_steamcmd_failure_recovers_service():
    service = _mock_service()
    # steamcmd 실패 후 상태 확인 시 stopped → 재시작 시도
    service.get_service_state.side_effect = ['running', 'stopped']
    with patch('service.palworld_service.PalworldService', return_value=service), \
         patch.object(updater, '_run_steamcmd_update', side_effect=RuntimeError('steamcmd exit 8')):
        updater._run_update()
    assert updater._state['status'] == 'failed'
    assert 'steamcmd exit 8' in updater._state['error']
    service.start.assert_called()  # 복구 재시작


def test_get_state_includes_version_and_log():
    updater._log.append('line1')
    updater._version['local_build'] = '100'
    s = updater.get_state()
    assert s['status'] == 'idle' and s['local_build'] == '100' and s['log'] == ['line1']
```

**Step 4: palworld_updater.py 구현** (전체 코드)

```python
"""
Palworld 서버 바이너리 업데이트
SteamCMD로 새 빌드 감지(appmanifest vs app_info_print) 및 업데이트 실행.
백업 → 서비스 중지 → app_update → 서비스 시작. 진행 상태/출력은 전역 링버퍼로 관리.
"""
import re
import time
import logging
import threading
import subprocess
from collections import deque
from datetime import datetime

from config.palworld_config import (
    STEAMCMD_EXE, PALWORLD_APP_ID, APP_MANIFEST_PATH,
    UPDATE_CHECK_INTERVAL_SEC, UPDATE_LOG_MAXLEN,
)
from service import audit_service
from service.audit_service import AuditCategory, AuditAction

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state = {
    'status': 'idle',      # idle | running | done | failed
    'step': None,          # backup | stop | download | start
    'trigger': None,       # manual | auto
    'error': None,
    'started_at': None,
    'finished_at': None,
}
_log = deque(maxlen=UPDATE_LOG_MAXLEN)
_version = {
    'local_build': None,
    'remote_build': None,
    'update_available': None,   # True | False | None(판단 불가)
    'checked_at': None,
}


def get_local_buildid():
    """설치된 서버 빌드 ID — steamapps/appmanifest_2394010.acf에서 파싱"""
    try:
        with open(APP_MANIFEST_PATH, 'r', encoding='utf-8', errors='replace') as f:
            m = re.search(r'"buildid"\s+"(\d+)"', f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def parse_remote_buildid(app_info_output):
    """steamcmd app_info_print 출력에서 public 브랜치 buildid 추출"""
    m = re.search(r'"public"\s*\{[^{}]*?"buildid"\s*"(\d+)"', app_info_output)
    return m.group(1) if m else None


def get_remote_buildid():
    """Steam의 최신 public 빌드 ID 조회 (steamcmd, 최대 3분)"""
    try:
        result = subprocess.run(
            [STEAMCMD_EXE, '+login', 'anonymous',
             '+app_info_update', '1', '+app_info_print', PALWORLD_APP_ID, '+quit'],
            capture_output=True, text=True, errors='replace', timeout=180
        )
        return parse_remote_buildid(result.stdout or '')
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f'원격 빌드 조회 실패: {e}')
        return None


def check_for_update():
    local = get_local_buildid()
    remote = get_remote_buildid()
    available = (local != remote) if (local and remote) else None
    _version.update({
        'local_build': local, 'remote_build': remote,
        'update_available': available,
        'checked_at': datetime.now().isoformat(timespec='seconds'),
    })
    return dict(_version)


def get_state():
    with _lock:
        state = dict(_state)
    state.update(_version)
    state['log'] = list(_log)
    return state


def start_update(trigger, actor_ip):
    """업데이트 시작. 이미 진행 중이면 False. 감사 기록은 여기서(트리거·행위자 포함)."""
    with _lock:
        if _state['status'] == 'running':
            return False
        _state.update({
            'status': 'running', 'step': 'backup', 'trigger': trigger,
            'error': None, 'finished_at': None,
            'started_at': datetime.now().isoformat(timespec='seconds'),
        })
    _log.clear()
    _log.append(f'[update] 서버 업데이트 시작 (trigger={trigger})')
    audit_service.record(
        AuditCategory.PALWORLD, AuditAction.SERVER_UPDATE, actor_ip,
        {'trigger': trigger, 'local_build': _version.get('local_build'),
         'remote_build': _version.get('remote_build')})
    threading.Thread(target=_run_update, daemon=True).start()
    return True


def _set_step(step):
    with _lock:
        _state['step'] = step


def _run_steamcmd_update():
    """steamcmd app_update 실행 — 출력을 라인 단위로 링버퍼에 스트리밍"""
    proc = subprocess.Popen(
        [STEAMCMD_EXE, '+login', 'anonymous',
         '+app_update', PALWORLD_APP_ID, 'validate', '+quit'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors='replace', bufsize=1
    )
    success_seen = False
    for line in proc.stdout:
        line = line.strip()
        if line:
            _log.append(line)
            if 'Success!' in line:
                success_seen = True
    code = proc.wait(timeout=3600)
    # steamcmd는 성공해도 0이 아닌 코드를 내는 경우가 있어 출력의 Success!를 함께 본다
    if not success_seen and code != 0:
        raise RuntimeError(f'steamcmd 실패 (exit {code})')


def _run_update():
    from service.palworld_service import PalworldService  # 지연 임포트 (순환 방지)
    service = PalworldService()
    try:
        _set_step('backup')
        try:
            backup = service.create_backup()
            _log.append(f"[backup] 완료: {backup.get('name')}")
        except Exception as e:
            logger.warning(f'업데이트 전 백업 실패(계속 진행): {e}')
            _log.append(f'[backup] 실패 — 계속 진행: {e}')

        _set_step('stop')
        if service.get_service_state() == 'running':
            service.stop()
        _log.append('[stop] 서비스 중지 완료')

        _set_step('download')
        _run_steamcmd_update()
        _log.append('[download] 새 빌드 설치 완료')

        _set_step('start')
        service.start()
        _log.append('[start] 서비스 시작 완료')

        # 로컬 빌드 갱신 → 배지가 "최신 상태"로 돌아온다
        local = get_local_buildid()
        remote = _version.get('remote_build')
        _version.update({
            'local_build': local,
            'update_available': (local != remote) if (local and remote) else None,
        })
        with _lock:
            _state.update({'status': 'done', 'step': None,
                           'finished_at': datetime.now().isoformat(timespec='seconds')})
        logger.info('팰월드 서버 업데이트 완료')
    except Exception as e:
        logger.error(f'팰월드 서버 업데이트 실패: {e}')
        _log.append(f'[error] {e}')
        # 실패해도 서버를 방치하지 않는다 — 구버전으로라도 재기동 시도
        try:
            if service.get_service_state() != 'running':
                service.start()
                _log.append('[recover] 서비스 재시작(기존 버전) 완료')
        except Exception as recover_error:
            _log.append(f'[recover] 서비스 재시작 실패: {recover_error}')
        with _lock:
            _state.update({'status': 'failed', 'step': None, 'error': str(e),
                           'finished_at': datetime.now().isoformat(timespec='seconds')})


def _count_players(service):
    """자동 업데이트 판단용 접속자 수. 판단 불가(REST 다운 등)면 0으로 간주 —
    서버가 비정상인 상황이면 어차피 업데이트가 이득이다."""
    try:
        status = service.get_status()
        if status['state'] != 'running':
            return 0
        metrics = status.get('metrics') or {}
        n = metrics.get('currentplayernum')
        return int(n) if n is not None else 0
    except Exception:
        return 0


def auto_check_loop(interval_sec=UPDATE_CHECK_INTERVAL_SEC):
    """새 빌드 자동 감지 루프 (데몬 스레드). 감지 시 접속자 0명이면 자동 업데이트."""
    from service.palworld_service import PalworldService
    service = PalworldService()
    while True:
        try:
            info = check_for_update()
            if info['update_available'] and get_state()['status'] != 'running':
                players = _count_players(service)
                if players == 0:
                    logger.info('새 빌드 감지 → 자동 업데이트 시작')
                    start_update('auto', 'system')
                else:
                    logger.info(f'새 빌드 감지, 접속자 {players}명 → 다음 주기에 재시도')
        except Exception as e:
            logger.warning(f'자동 업데이트 체크 실패: {e}')
        time.sleep(interval_sec)
```

**Step 5: 라우터 추가** (palworld_router.py — logs() 아래에 배치)

```python
@palworld_bp.route('/palworld/update', methods=['POST'])
def update_server():
    """서버 바이너리 업데이트 시작 (백업→중지→steamcmd→시작, 백그라운드 실행)"""
    if not palworld_updater.start_update('manual', _client_ip()):
        return jsonify({'error': '이미 업데이트가 진행 중입니다'}), 409
    return jsonify({'started': True}), 202


@palworld_bp.route('/palworld/update/status', methods=['GET'])
def update_status():
    """업데이트 진행 상태 + 버전 정보 + 출력 로그 (UI 폴링용)"""
    return jsonify(palworld_updater.get_state()), 200


@palworld_bp.route('/palworld/update/check', methods=['POST'])
def update_check():
    """최신 빌드 즉시 확인 (동기 — steamcmd 조회로 수십 초 걸릴 수 있음)"""
    try:
        return jsonify(palworld_updater.check_for_update()), 200
    except Exception as e:
        logger.error(f"Update check error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

임포트 추가: `from service import palworld_updater` (기존 `from service import audit_service` 옆).
감사 기록은 `start_update()` 내부에서 수행하므로 라우터에서 record를 호출하지 않는다.

**Step 6: 라우터 테스트 추가** (test_palworld_router.py)

```python
def test_update_starts_and_returns_202(client):
    with patch('router.palworld_router.palworld_updater.start_update', return_value=True) as mock_start:
        resp = client.post('/palworld/update')
    assert resp.status_code == 202
    assert mock_start.call_args[0][0] == 'manual'


def test_update_conflict_when_already_running(client):
    with patch('router.palworld_router.palworld_updater.start_update', return_value=False):
        resp = client.post('/palworld/update')
    assert resp.status_code == 409


def test_update_status_returns_state(client):
    fake = {'status': 'running', 'step': 'download', 'log': ['x'], 'update_available': True}
    with patch('router.palworld_router.palworld_updater.get_state', return_value=fake):
        resp = client.get('/palworld/update/status')
    assert resp.status_code == 200
    assert resp.get_json()['step'] == 'download'


def test_update_check_returns_version_info(client):
    fake = {'local_build': '1', 'remote_build': '2', 'update_available': True}
    with patch('router.palworld_router.palworld_updater.check_for_update', return_value=fake):
        resp = client.post('/palworld/update/check')
    assert resp.status_code == 200
    assert resp.get_json()['update_available'] is True
```

**Step 7: run.py — 자동 체크 스레드 시작**

기존 이벤트 폴러 시작 블록 바로 아래에 동일 패턴으로:

```python
from service import palworld_updater
threading.Thread(target=palworld_updater.auto_check_loop, daemon=True,
                 name='palworld-update-checker').start()
```

(run.py에 `import threading`이 없으면 추가. 폴러가 조건부 기동이면 같은 조건 안에 넣는다.)

**Step 8: Swagger 문서화** — palworld_swagger.py의 기존 엔드포인트 문서 패턴을 그대로 따라 update/update-status/update-check 3개 추가.

**Step 9: 전체 테스트 → 커밋**

```bash
cd suh-ai-server/flask && python -m pytest -q
```
Expected: 기존 99 + 신규 전부 PASS.

```bash
git add -A suh-ai-server/flask
git commit -m "팰월드 서버 업데이트 : feat : SteamCMD 업데이트 실행·자동 감지 백엔드 https://github.com/Cassiiopeia/suh-project-control/issues/73"
```

---

### Task 2: 프론트 — 배지·버튼·진행 패널

**Files:**
- Modify: `suh-ai-server/flask/templates/admin/palworld.html`
- Modify: `suh-ai-server/flask/static/js/palworld.js`
- CSS 재빌드: `suh-ai-server/flask/frontend` → `npm run build`

**Interfaces:**
- Consumes: `GET ../palworld/update/status`, `POST ../palworld/update`, `POST ../palworld/update/check` (Task 1)

**Step 1: palworld.html — 서버 상태 카드에 업데이트 영역 추가**

보조 지표 stats 블록(`stat-version` 포함된 div) 바로 아래, 스파크라인 grid 위에 삽입:

```html
      <!-- 서버 빌드 업데이트 -->
      <div class="flex flex-wrap items-center gap-2">
        <span id="update-badge" class="badge badge-ghost">빌드 확인 전</span>
        <span id="update-builds" class="text-xs opacity-60 font-mono"></span>
        <div class="ml-auto flex gap-2">
          <button id="btn-update-check" class="btn btn-ghost btn-sm" onclick="checkServerUpdate()">
            <i data-lucide="refresh-cw" class="size-4"></i>업데이트 확인
          </button>
          <button id="btn-update" class="btn btn-info btn-sm" onclick="startServerUpdate()">
            <i data-lucide="download" class="size-4"></i>서버 업데이트
          </button>
        </div>
      </div>
      <div id="update-progress" class="hidden bg-base-200 rounded-box p-3 space-y-2">
        <div class="flex items-center gap-2 text-sm">
          <span id="update-spinner" class="loading loading-spinner loading-sm"></span>
          <span id="update-step" class="font-medium"></span>
        </div>
        <pre id="update-log" class="bg-base-300 rounded-box text-xs leading-5 overflow-auto max-h-48 p-3"></pre>
      </div>
```

lucide 아이콘 `download`·`refresh-cw`는 로컬 번들(1.24.0)에 존재(refresh-cw는 이미 사용 중). 번들에 download가 없으면 `hard-drive-download` 대신 확인 후 존재하는 아이콘 사용.

**Step 2: palworld.js — 업데이트 로직 추가** (copyGuide와 initLogViewer 사이에 삽입)

```javascript
/* ── 서버 바이너리 업데이트 ── */
const UPDATE_STEP_LABELS = {
  backup: '세이브 백업 중…', stop: '서버 중지 중…',
  download: '새 버전 다운로드 중…', start: '서버 시작 중…',
};
let updatePollTimer = null;
let updateWasRunning = false;

function renderUpdateState(s) {
  const badge = document.getElementById('update-badge');
  const builds = document.getElementById('update-builds');
  if (!badge) return;
  if (s.status === 'running') {
    badge.className = 'badge badge-info';
    badge.textContent = '업데이트 진행 중';
  } else if (s.update_available === true) {
    badge.className = 'badge badge-warning';
    badge.textContent = '업데이트 필요';
  } else if (s.update_available === false) {
    badge.className = 'badge badge-success';
    badge.textContent = '최신 상태';
  } else {
    badge.className = 'badge badge-ghost';
    badge.textContent = s.checked_at ? '버전 판단 불가' : '빌드 확인 전';
  }
  builds.textContent = (s.local_build ? '빌드 ' + s.local_build : '') +
    (s.update_available === true && s.remote_build ? ' → ' + s.remote_build : '');

  const running = s.status === 'running';
  const showPanel = running || ((s.status === 'done' || s.status === 'failed') && s.log && s.log.length);
  const panel = document.getElementById('update-progress');
  panel.classList.toggle('hidden', !showPanel);
  document.getElementById('update-spinner').classList.toggle('hidden', !running);
  document.getElementById('update-step').textContent =
    running ? (UPDATE_STEP_LABELS[s.step] || '진행 중…')
      : s.status === 'done' ? '업데이트 완료'
      : s.status === 'failed' ? '업데이트 실패: ' + (s.error || '') : '';
  if (showPanel) {
    const pre = document.getElementById('update-log');
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
    pre.textContent = (s.log || []).join('\n');
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }

  if (updateWasRunning && s.status === 'done') {
    showToast('서버 업데이트 완료', 'success');
    refreshStatus();
  }
  if (updateWasRunning && s.status === 'failed') {
    showToast('서버 업데이트 실패: ' + (s.error || ''), 'error');
  }
  updateWasRunning = running;

  if (running && !updatePollTimer) updatePollTimer = setInterval(pollUpdateStatus, 3000);
  if (!running && updatePollTimer) { clearInterval(updatePollTimer); updatePollTimer = null; }
}

async function pollUpdateStatus() {
  try {
    const resp = await apiFetch(API + '/update/status');
    renderUpdateState(await resp.json());
  } catch (e) { /* 401은 modal 처리 */ }
}

async function checkServerUpdate() {
  const btn = document.getElementById('btn-update-check');
  btn.disabled = true;
  showToast('최신 빌드 확인 중… (최대 1~2분)', 'info');
  try {
    const resp = await apiFetch(API + '/update/check', { method: 'POST' });
    const data = await resp.json();
    if (data.update_available === true) showToast('새 버전이 있습니다 — 서버 업데이트를 실행하세요', 'warning');
    else if (data.update_available === false) showToast('이미 최신 버전입니다', 'success');
    else showToast('버전을 판단할 수 없습니다 (스팀 조회 실패)', 'error');
    await pollUpdateStatus();
  } catch (e) { showToast(String(e), 'error'); }
  btn.disabled = false;
}

async function startServerUpdate() {
  if (!(await confirmAction('서버를 중지하고 새 버전을 다운로드합니다. 수 분이 걸리고 접속 중인 플레이어는 끊깁니다. 진행할까요?'))) return;
  try {
    const resp = await apiFetch(API + '/update', { method: 'POST' });
    if (resp.status === 409) { showToast('이미 업데이트가 진행 중입니다', 'warning'); return; }
    showToast('서버 업데이트 시작', 'info');
    await pollUpdateStatus();
  } catch (e) { showToast(String(e), 'error'); }
}
```

DOMContentLoaded 블록에 `pollUpdateStatus();` 한 줄 추가 (initLogViewer() 다음) — 페이지 진입 시 진행 중 업데이트 복원 + 버전 배지 반영.

**Step 3: CSS 재빌드 + 검증**

```bash
cd suh-ai-server/flask/frontend && npm run build
grep -c "badge-info\|loading-spinner\|max-h-48" ../static/css/app.css
```
Expected: 0이 아닌 값 (신규 클래스 포함 확인). lucide 번들에 `download` 아이콘 존재 확인:
```bash
grep -c '"download"' ../static/js/lucide-icons.js 2>/dev/null || grep -rn 'download' ../static/js/ | head -3
```
없으면 존재하는 아이콘으로 교체.

**Step 4: 렌더 스모크 + 전체 테스트 → 커밋**

```bash
cd suh-ai-server/flask && python -m pytest -q
```

```bash
git add -A suh-ai-server/flask
git commit -m "팰월드 서버 업데이트 : feat : 업데이트 배지·버튼·실시간 진행 패널 UI https://github.com/Cassiiopeia/suh-project-control/issues/73"
```
