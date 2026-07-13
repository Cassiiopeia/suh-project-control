# Palworld 서버 구축 + DaisyUI 관리자 페이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이 Windows PC에 Palworld 데디케이티드 서버를 NSSM 서비스로 구축하고, suh-ai-server(Flask)에 DaisyUI 관리자 페이지(대시보드 + 팰월드 제어)를 추가한다.

**Architecture:** Flask에 기존 라우터/서비스 계층 패턴 그대로 `palworld_router`(REST API) + `admin_router`(Jinja2 페이지)를 추가. 프로세스 제어는 NSSM 서비스(`PalServer`), 접속자/메트릭은 Palworld 공식 REST API(:8212, localhost)를 중계. 인증은 기존 nginx X-API-Key 재사용(페이지·정적파일만 public).

**Tech Stack:** Flask 3.0, pytest, PowerShell(설치 스크립트), NSSM, SteamCMD, Tailwind CSS v4 + daisyUI v5 (Tailwind CLI 빌드, 산출물 커밋)

**관련 이슈:** https://github.com/Cassiiopeia/suh-project-control/issues/46
**설계 문서:** `docs/superpowers/specs/2026-07-13-palworld-admin-design.md`

## Global Constraints

- 모든 커밋 메시지 형식: `Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : {설명} https://github.com/Cassiiopeia/suh-project-control/issues/46` + 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 작업 브랜치: `main` (사용자 결정)
- PalServer 설치 경로: `C:\AI\palworld\steamcmd\steamapps\common\PalServer`
- NSSM 서비스명: `PalServer` / 기존 Flask 서비스명: `FlaskOCRService`
- Palworld 공식 REST API: `http://127.0.0.1:8212` (Basic 인증 `admin:{AdminPassword}`)
- 백업 경로: `C:\AI\palworld\backups\{yyyyMMdd_HHmmss}`
- Flask 소스 위치(repo): `suh-ai-server/flask` — 운영 배포 경로는 `C:\AI\suh-ai-server\flask` (기존 CI가 동기화)
- ini 저장은 서버 가동 중이면 반드시 409 — 절대 가동 중 파일을 쓰지 않는다
- 페이지/JS의 모든 URL은 상대경로 (외부 `/api/flask/` prefix 유무 모두 동작해야 함)
- 테스트 실행 위치: `suh-ai-server/flask` 디렉토리에서 `python -m pytest test/ -v`
- Python 실행: `C:\Users\chan4\AppData\Local\Programs\Python\Python313\python.exe` (python3 별칭 금지 — Windows Store stub)

## File Structure

```
suh-ai-server/
├─ scripts/
│   └─ setup-palworld.ps1          [신규] 서버 설치·NSSM·방화벽·백업 스케줄러 (1회 실행)
├─ config/
│   └─ nginx.conf                  [수정] admin/static public 규칙 추가
└─ flask/
    ├─ app.py                      [수정] palworld_bp, admin_bp 등록
    ├─ requirements-dev.txt        [신규] pytest
    ├─ config/
    │   └─ palworld_config.py      [신규] 경로/포트/서비스명 상수
    ├─ service/
    │   ├─ palworld_ini.py         [신규] OptionSettings 파서/직렬화 (순수 함수)
    │   └─ palworld_service.py     [신규] NSSM 제어, REST 중계, ini, 로그, 백업
    ├─ router/
    │   ├─ palworld_router.py      [신규] /palworld/* REST API
    │   ├─ palworld_swagger.py     [신규] Swagger paths dict
    │   ├─ admin_router.py         [신규] /admin, /admin/palworld 페이지
    │   └─ swagger_router.py       [수정] palworld paths merge
    ├─ frontend/
    │   ├─ package.json            [신규] tailwindcss v4 + daisyui v5
    │   └─ input.css               [신규]
    ├─ templates/admin/
    │   ├─ dashboard.html          [신규]
    │   └─ palworld.html           [신규]
    ├─ static/
    │   ├─ css/app.css             [빌드 산출물, 커밋]
    │   └─ js/
    │       ├─ admin-common.js     [신규] API Key modal + fetch 래퍼
    │       └─ palworld.js         [신규]
    └─ test/
        ├─ conftest.py             [신규]
        ├─ test_palworld_ini.py    [신규]
        ├─ test_palworld_service.py[신규]
        └─ test_palworld_router.py [신규]
```

---

### Task 1: Palworld 서버 설치 스크립트 (setup-palworld.ps1)

**Files:**
- Create: `suh-ai-server/scripts/setup-palworld.ps1`

**Interfaces:**
- Produces: NSSM 서비스 `PalServer`, ini 파일 `C:\AI\palworld\steamcmd\steamapps\common\PalServer\Pal\Saved\Config\WindowsServer\PalWorldSettings.ini` (RESTAPIEnabled=True, AdminPassword 설정), 백업 스케줄러. Task 2~5의 서비스 코드가 이 경로·서비스명에 의존.

- [ ] **Step 1: 스크립트 작성**

```powershell
#Requires -Version 5.1
#Requires -RunAsAdministrator

<#
.SYNOPSIS
    Palworld Dedicated Server 설치 및 NSSM 서비스 등록 (1회 실행)
.DESCRIPTION
    SteamCMD 설치 -> PalServer 설치 -> ini 초기화 -> NSSM 서비스 등록 ->
    방화벽 개방 -> 일일 백업 스케줄러 등록
#>
param(
    [string]$AdminPassword = "palworld-admin-2026",
    [string]$ServerName = "Suh Palworld Server",
    [string]$ServerPassword = ""
)

$ErrorActionPreference = "Stop"

$baseDir = "C:\AI\palworld"
$steamCmdDir = Join-Path $baseDir "steamcmd"
$steamCmdExe = Join-Path $steamCmdDir "steamcmd.exe"
$palServerDir = Join-Path $steamCmdDir "steamapps\common\PalServer"
$palServerExe = Join-Path $palServerDir "PalServer.exe"
$configDir = Join-Path $palServerDir "Pal\Saved\Config\WindowsServer"
$iniPath = Join-Path $configDir "PalWorldSettings.ini"
$defaultIniPath = Join-Path $palServerDir "DefaultPalWorldSettings.ini"
$logsDir = Join-Path $baseDir "logs"
$backupDir = Join-Path $baseDir "backups"
$serviceName = "PalServer"

# 1. 디렉토리 생성
foreach ($dir in @($baseDir, $steamCmdDir, $logsDir, $backupDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}
Write-Host "[SUCCESS] Directories ready: $baseDir"

# 2. SteamCMD 설치
if (-not (Test-Path $steamCmdExe)) {
    Write-Host "[INFO] Downloading SteamCMD..."
    $zipPath = Join-Path $env:TEMP "steamcmd.zip"
    Invoke-WebRequest -Uri "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $steamCmdDir -Force
    Remove-Item $zipPath
    Write-Host "[SUCCESS] SteamCMD installed"
} else {
    Write-Host "[INFO] SteamCMD already installed"
}

# 3. PalServer 설치/업데이트 (수 GB 다운로드 - 시간 소요)
Write-Host "[INFO] Installing/updating Palworld Dedicated Server (app 2394010)..."
& $steamCmdExe +login anonymous +app_update 2394010 validate +quit
if (-not (Test-Path $palServerExe)) {
    Write-Host "[ERROR] PalServer.exe not found after install: $palServerExe"
    exit 1
}
Write-Host "[SUCCESS] PalServer installed: $palServerDir"

# 4. ini 초기화 (DefaultPalWorldSettings.ini 복사 후 값 수정)
if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Force -Path $configDir | Out-Null }
if (-not (Test-Path $iniPath)) {
    Copy-Item $defaultIniPath $iniPath
    Write-Host "[SUCCESS] PalWorldSettings.ini created from default"
}

# OptionSettings 라인의 주요 값 수정 (서버 정지 상태에서만 실행되므로 안전)
$content = Get-Content $iniPath -Raw
$replacements = @{
    'ServerName="[^"]*"'      = "ServerName=`"$ServerName`""
    'AdminPassword="[^"]*"'   = "AdminPassword=`"$AdminPassword`""
    'ServerPassword="[^"]*"'  = "ServerPassword=`"$ServerPassword`""
    'RESTAPIEnabled=\w+'      = 'RESTAPIEnabled=True'
    'RESTAPIPort=\d+'         = 'RESTAPIPort=8212'
}
foreach ($pattern in $replacements.Keys) {
    $content = $content -replace $pattern, $replacements[$pattern]
}
Set-Content -Path $iniPath -Value $content -NoNewline -Encoding UTF8
Write-Host "[SUCCESS] ini configured (RESTAPIEnabled=True, RESTAPIPort=8212)"

# 5. NSSM 서비스 등록
$nssmPath = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $nssmPath) {
    Write-Host "[ERROR] NSSM not found. Install with: choco install nssm"
    exit 1
}
$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if (-not $existing) {
    & nssm install $serviceName $palServerExe "-port=8211 -players=32 -useperfthreads -NoAsyncLoadingThread -UseMultithreadForDS"
    & nssm set $serviceName AppDirectory $palServerDir
    & nssm set $serviceName DisplayName "Palworld Dedicated Server"
    & nssm set $serviceName Start SERVICE_AUTO_START
    & nssm set $serviceName AppStdout "$logsDir\palserver-stdout.log"
    & nssm set $serviceName AppStderr "$logsDir\palserver-stderr.log"
    & nssm set $serviceName AppStopMethodConsole 15000
    Write-Host "[SUCCESS] NSSM service '$serviceName' created"
} else {
    Write-Host "[INFO] Service '$serviceName' already exists"
}

# 6. 방화벽 개방 (UDP 8211 게임, UDP 27015 스팀 서버목록)
foreach ($rule in @(
    @{ Name = "Palworld-Game-8211";  Port = 8211  },
    @{ Name = "Palworld-Steam-27015"; Port = 27015 }
)) {
    if (-not (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol UDP -LocalPort $rule.Port -Action Allow | Out-Null
        Write-Host "[SUCCESS] Firewall rule added: $($rule.Name)"
    }
}

# 7. 일일 백업 스케줄러 (매일 04:00, robocopy 미러가 아닌 신규 폴더 복사)
$taskName = "PalworldDailyBackup"
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    $saveDir = Join-Path $palServerDir "Pal\Saved\SaveGames"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
        "-NoProfile -Command `"robocopy '$saveDir' ('$backupDir\' + (Get-Date -Format yyyyMMdd_HHmmss)) /E`"" )
    $trigger = New-ScheduledTaskTrigger -Daily -At 4am
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -RunLevel Highest | Out-Null
    Write-Host "[SUCCESS] Daily backup task registered (04:00)"
}

# 8. 서비스 시작 및 REST API 검증
Write-Host "[INFO] Starting PalServer service..."
Start-Service -Name $serviceName
Start-Sleep -Seconds 30

$pair = "admin:$AdminPassword"
$headers = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair)) }
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8212/v1/api/info" -Headers $headers -TimeoutSec 10
    Write-Host "[SUCCESS] Palworld REST API responding: $($resp | ConvertTo-Json -Compress)"
} catch {
    Write-Host "[WARN] REST API not responding yet (server may still be loading): $($_.Exception.Message)"
}
Write-Host "[SUCCESS] setup-palworld.ps1 completed"
```

- [ ] **Step 2: 관리자 PowerShell로 실행 (다운로드 수 GB — 백그라운드 실행, 최대 30분)**

Run: `powershell -ExecutionPolicy Bypass -File suh-ai-server\scripts\setup-palworld.ps1` (관리자 권한 필요 — 비관리자 세션이면 사용자에게 관리자 터미널 실행 요청)
Expected: `[SUCCESS] setup-palworld.ps1 completed`

- [ ] **Step 3: 서비스·REST 검증**

Run: `Get-Service PalServer; Invoke-RestMethod -Uri "http://127.0.0.1:8212/v1/api/info" -Headers @{Authorization="Basic "+[Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:palworld-admin-2026"))}`
Expected: Status `Running`, JSON에 `version`/`servername` 포함

- [ ] **Step 4: Commit**

```bash
git add suh-ai-server/scripts/setup-palworld.ps1
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : SteamCMD 기반 서버 설치 및 NSSM 서비스 등록 스크립트 추가 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

### Task 2: pytest 인프라 + palworld_config

**Files:**
- Create: `suh-ai-server/flask/requirements-dev.txt`
- Create: `suh-ai-server/flask/test/conftest.py`
- Create: `suh-ai-server/flask/config/palworld_config.py`

**Interfaces:**
- Produces: `palworld_config`의 상수 — `PALSERVER_DIR`, `INI_PATH`, `SAVE_DIR`, `BACKUP_DIR`, `LOG_FILE`, `SERVICE_NAME`, `REST_BASE_URL`, `STRING_KEYS`, `EDITABLE_KEYS`. Task 3~5가 import.

- [ ] **Step 1: requirements-dev.txt 작성**

```
pytest==8.3.4
```

- [ ] **Step 2: conftest.py 작성** (flask 디렉토리를 import path에 추가)

```python
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
```

- [ ] **Step 3: palworld_config.py 작성**

```python
"""
Palworld server management configuration
"""
import os

PALWORLD_BASE_DIR = r"C:\AI\palworld"
PALSERVER_DIR = os.path.join(PALWORLD_BASE_DIR, "steamcmd", "steamapps", "common", "PalServer")
INI_PATH = os.path.join(PALSERVER_DIR, "Pal", "Saved", "Config", "WindowsServer", "PalWorldSettings.ini")
SAVE_DIR = os.path.join(PALSERVER_DIR, "Pal", "Saved", "SaveGames")
BACKUP_DIR = os.path.join(PALWORLD_BASE_DIR, "backups")
LOG_FILE = os.path.join(PALWORLD_BASE_DIR, "logs", "palserver-stdout.log")

SERVICE_NAME = "PalServer"
REST_BASE_URL = "http://127.0.0.1:8212"

# OptionSettings에서 문자열로 취급해 따옴표를 붙여야 하는 키
STRING_KEYS = {
    "ServerName", "ServerDescription", "AdminPassword", "ServerPassword",
    "PublicIP", "Region", "BanListURL", "LogFormatType",
}

# 관리자 페이지에서 편집 허용하는 키 (그 외 키는 PUT 시 무시)
EDITABLE_KEYS = [
    "ServerName", "ServerDescription", "ServerPassword", "ServerPlayerMaxNum",
    "bCrossplay", "ExpRate", "PalCaptureRate", "DeathPenalty",
    "bEnablePlayerToPlayerDamage", "DayTimeSpeedRate", "NightTimeSpeedRate",
    "PalSpawnNumRate", "CollectionDropRate", "WorkSpeedRate",
]
```

- [ ] **Step 4: pytest 설치 및 빈 실행 확인**

Run: `cd suh-ai-server/flask && python -m pip install -r requirements-dev.txt && python -m pytest test/ -v`
Expected: `no tests ran` (에러 없이 종료)

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/requirements-dev.txt suh-ai-server/flask/test/conftest.py suh-ai-server/flask/config/palworld_config.py
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : pytest 인프라 및 palworld 설정 상수 추가 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

### Task 3: OptionSettings ini 파서 (TDD)

**Files:**
- Create: `suh-ai-server/flask/service/palworld_ini.py`
- Test: `suh-ai-server/flask/test/test_palworld_ini.py`

**Interfaces:**
- Produces:
  - `parse_option_settings(text: str) -> dict[str, str]` — ini 전문에서 OptionSettings 키·raw값 dict 반환. OptionSettings 라인 없으면 `ValueError`
  - `update_option_settings(text: str, changes: dict[str, str]) -> str` — 값 치환한 새 ini 전문 반환 (다른 줄 보존). `STRING_KEYS`는 자동 따옴표 래핑
  - Task 4의 `PalworldService.get_settings/update_settings`가 사용

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""test_palworld_ini.py"""
import pytest
from service.palworld_ini import parse_option_settings, update_option_settings

SAMPLE = '''[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,ServerName="My, Server",ServerPassword="",ServerPlayerMaxNum=32,bCrossplay=False,RESTAPIEnabled=True)
'''


def test_parse_basic_values():
    result = parse_option_settings(SAMPLE)
    assert result["Difficulty"] == "None"
    assert result["ServerPlayerMaxNum"] == "32"
    assert result["bCrossplay"] == "False"


def test_parse_quoted_string_with_comma():
    result = parse_option_settings(SAMPLE)
    assert result["ServerName"] == '"My, Server"'


def test_parse_missing_option_settings_raises():
    with pytest.raises(ValueError):
        parse_option_settings("[/Script/Pal.PalGameWorldSettings]\n")


def test_update_preserves_other_keys_and_lines():
    updated = update_option_settings(SAMPLE, {"ServerPlayerMaxNum": "16"})
    result = parse_option_settings(updated)
    assert result["ServerPlayerMaxNum"] == "16"
    assert result["ServerName"] == '"My, Server"'
    assert updated.startswith("[/Script/Pal.PalGameWorldSettings]")


def test_update_wraps_string_keys_in_quotes():
    updated = update_option_settings(SAMPLE, {"ServerName": "팰 사냥터"})
    result = parse_option_settings(updated)
    assert result["ServerName"] == '"팰 사냥터"'


def test_update_boolean_passthrough():
    updated = update_option_settings(SAMPLE, {"bCrossplay": "True"})
    assert parse_option_settings(updated)["bCrossplay"] == "True"


def test_roundtrip_no_changes_is_identical():
    assert update_option_settings(SAMPLE, {}) == SAMPLE
```

- [ ] **Step 2: 실패 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_palworld_ini.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'service.palworld_ini'`

- [ ] **Step 3: 구현**

```python
"""
PalWorldSettings.ini OptionSettings 파서/직렬화
OptionSettings=(k=v,k=v,...) 한 줄 포맷 전용. 따옴표 내 콤마를 안전하게 처리한다.
"""
import re
from config.palworld_config import STRING_KEYS

_OPTION_RE = re.compile(r'^(OptionSettings=\()(.*)(\))\s*$', re.MULTILINE)


def _split_pairs(inner: str) -> list[str]:
    parts, buf, in_quotes = [], [], False
    for ch in inner:
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == ',' and not in_quotes:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf))
    return parts


def parse_option_settings(text: str) -> dict:
    match = _OPTION_RE.search(text)
    if not match:
        raise ValueError("OptionSettings line not found in ini content")
    result = {}
    for pair in _split_pairs(match.group(2)):
        if '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        result[key.strip()] = value.strip()
    return result


def update_option_settings(text: str, changes: dict) -> str:
    current = parse_option_settings(text)
    for key, value in changes.items():
        value = str(value)
        if key in STRING_KEYS and not (value.startswith('"') and value.endswith('"')):
            value = f'"{value}"'
        current[key] = value
    serialized = ','.join(f'{k}={v}' for k, v in current.items())
    return _OPTION_RE.sub(lambda m: f'{m.group(1)}{serialized}{m.group(3)}', text, count=1)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_palworld_ini.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/service/palworld_ini.py suh-ai-server/flask/test/test_palworld_ini.py
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : PalWorldSettings.ini OptionSettings 파서 구현 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

### Task 4: PalworldService (TDD, 외부 호출 mock)

**Files:**
- Create: `suh-ai-server/flask/service/palworld_service.py`
- Test: `suh-ai-server/flask/test/test_palworld_service.py`

**Interfaces:**
- Consumes: `palworld_ini.parse_option_settings/update_option_settings`, `palworld_config` 상수
- Produces (Task 5의 라우터가 사용):
  - `class ServerRunningError(Exception)`
  - `class PalworldService:`
    - `get_service_state() -> str` — `'running' | 'stopped' | 'not_installed'`
    - `start() / stop() / restart() -> None` (실패 시 `RuntimeError`)
    - `get_status() -> dict` — `{state, rest_available, info, players, metrics}`
    - `get_settings() -> dict` — `{settings: {k: v}, editable_keys: [...]}`
    - `update_settings(changes: dict) -> dict` — running이면 `ServerRunningError`
    - `tail_logs(lines: int = 200) -> list[str]`
    - `list_backups() -> list[dict]` — `[{name, size_mb, created}]` 최신순
    - `create_backup() -> dict` — `{name}`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""test_palworld_service.py"""
import pytest
from unittest.mock import patch, MagicMock
from service.palworld_service import PalworldService, ServerRunningError

SAMPLE_INI = '''[/Script/Pal.PalGameWorldSettings]
OptionSettings=(ServerName="Test",AdminPassword="secret",ServerPlayerMaxNum=32,bCrossplay=False,RESTAPIEnabled=True)
'''


@pytest.fixture
def service():
    return PalworldService()


def _sc_result(stdout, returncode=0):
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


def test_get_service_state_running(service):
    with patch('service.palworld_service.subprocess.run',
               return_value=_sc_result("SERVICE_NAME: PalServer\n        STATE : 4  RUNNING\n")):
        assert service.get_service_state() == 'running'


def test_get_service_state_stopped(service):
    with patch('service.palworld_service.subprocess.run',
               return_value=_sc_result("SERVICE_NAME: PalServer\n        STATE : 1  STOPPED\n")):
        assert service.get_service_state() == 'stopped'


def test_get_service_state_not_installed(service):
    with patch('service.palworld_service.subprocess.run',
               return_value=_sc_result("", returncode=1060)):
        assert service.get_service_state() == 'not_installed'


def test_update_settings_blocked_while_running(service):
    with patch.object(service, 'get_service_state', return_value='running'):
        with pytest.raises(ServerRunningError):
            service.update_settings({"ServerName": "New"})


def test_update_settings_writes_when_stopped(service, tmp_path):
    ini = tmp_path / "PalWorldSettings.ini"
    ini.write_text(SAMPLE_INI, encoding='utf-8')
    with patch.object(service, 'get_service_state', return_value='stopped'), \
         patch('service.palworld_service.INI_PATH', str(ini)):
        result = service.update_settings({"ServerName": "New"})
    assert result["settings"]["ServerName"] == '"New"'
    assert 'ServerName="New"' in ini.read_text(encoding='utf-8')


def test_update_settings_ignores_non_editable_keys(service, tmp_path):
    ini = tmp_path / "PalWorldSettings.ini"
    ini.write_text(SAMPLE_INI, encoding='utf-8')
    with patch.object(service, 'get_service_state', return_value='stopped'), \
         patch('service.palworld_service.INI_PATH', str(ini)):
        service.update_settings({"AdminPassword": "hacked", "ServerName": "OK"})
    text = ini.read_text(encoding='utf-8')
    assert 'AdminPassword="secret"' in text


def test_get_status_degrades_when_rest_down(service):
    with patch.object(service, 'get_service_state', return_value='running'), \
         patch('service.palworld_service.requests.get', side_effect=Exception("conn refused")):
        status = service.get_status()
    assert status['state'] == 'running'
    assert status['rest_available'] is False


def test_start_calls_powershell(service):
    with patch('service.palworld_service.subprocess.run', return_value=_sc_result("", 0)) as mock_run:
        service.start()
    args = mock_run.call_args[0][0]
    assert 'Start-Service' in ' '.join(args)
```

- [ ] **Step 2: 실패 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_palworld_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'service.palworld_service'`

- [ ] **Step 3: 구현**

```python
"""
Palworld server management service
NSSM 서비스 제어, 공식 REST API 중계, ini 관리, 로그, 백업
"""
import os
import shutil
import subprocess
import logging
from datetime import datetime

import requests

from config.palworld_config import (
    INI_PATH, SAVE_DIR, BACKUP_DIR, LOG_FILE,
    SERVICE_NAME, REST_BASE_URL, EDITABLE_KEYS,
)
from service.palworld_ini import parse_option_settings, update_option_settings

logger = logging.getLogger(__name__)


class ServerRunningError(Exception):
    """서버 가동 중에는 ini를 수정할 수 없다 (종료 시 덮어씌워져 유실됨)"""


class PalworldService:

    # --- 서비스 제어 ---

    def get_service_state(self) -> str:
        result = subprocess.run(
            ['sc', 'query', SERVICE_NAME],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return 'not_installed'
        if 'RUNNING' in result.stdout:
            return 'running'
        return 'stopped'

    def _service_command(self, verb: str):
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', f'{verb}-Service -Name {SERVICE_NAME} -ErrorAction Stop'],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f'{verb}-Service failed: {result.stderr.strip()}')

    def start(self):
        self._service_command('Start')

    def stop(self):
        self._service_command('Stop')

    def restart(self):
        self._service_command('Restart')

    # --- 상태 (공식 REST API 중계) ---

    def _rest_auth(self):
        admin_password = ''
        try:
            with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
                settings = parse_option_settings(f.read())
            admin_password = settings.get('AdminPassword', '""').strip('"')
        except (OSError, ValueError):
            pass
        return ('admin', admin_password)

    def get_status(self) -> dict:
        status = {
            'state': self.get_service_state(),
            'rest_available': False,
            'info': None,
            'players': [],
            'metrics': None,
        }
        if status['state'] != 'running':
            return status
        auth = self._rest_auth()
        try:
            info = requests.get(f'{REST_BASE_URL}/v1/api/info', auth=auth, timeout=3)
            players = requests.get(f'{REST_BASE_URL}/v1/api/players', auth=auth, timeout=3)
            metrics = requests.get(f'{REST_BASE_URL}/v1/api/metrics', auth=auth, timeout=3)
            status['info'] = info.json()
            status['players'] = players.json().get('players', [])
            status['metrics'] = metrics.json()
            status['rest_available'] = True
        except Exception as e:
            logger.warning(f'Palworld REST API unavailable: {e}')
        return status

    # --- 설정 ---

    def get_settings(self) -> dict:
        with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
            settings = parse_option_settings(f.read())
        return {'settings': settings, 'editable_keys': EDITABLE_KEYS}

    def update_settings(self, changes: dict) -> dict:
        if self.get_service_state() == 'running':
            raise ServerRunningError(
                'Server is running - stop the server before saving settings '
                '(changes would be overwritten on shutdown)'
            )
        filtered = {k: v for k, v in changes.items() if k in EDITABLE_KEYS}
        with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
        updated = update_option_settings(text, filtered)
        with open(INI_PATH, 'w', encoding='utf-8') as f:
            f.write(updated)
        logger.info(f'PalWorldSettings.ini updated: {list(filtered.keys())}')
        return {'settings': parse_option_settings(updated), 'editable_keys': EDITABLE_KEYS}

    # --- 로그 ---

    def tail_logs(self, lines: int = 200) -> list:
        lines = min(int(lines), 500)
        if not os.path.exists(LOG_FILE):
            return []
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        return [l.rstrip('\n\r') for l in all_lines[-lines:]]

    # --- 백업 ---

    def list_backups(self) -> list:
        if not os.path.isdir(BACKUP_DIR):
            return []
        backups = []
        for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
            path = os.path.join(BACKUP_DIR, name)
            if not os.path.isdir(path):
                continue
            size = sum(
                os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(path) for f in files
            )
            backups.append({
                'name': name,
                'size_mb': round(size / 1024 / 1024, 1),
                'created': datetime.fromtimestamp(os.path.getctime(path)).isoformat(),
            })
        return backups

    def create_backup(self) -> dict:
        if not os.path.isdir(SAVE_DIR):
            raise FileNotFoundError(f'SaveGames directory not found: {SAVE_DIR}')
        name = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest = os.path.join(BACKUP_DIR, name)
        shutil.copytree(SAVE_DIR, dest)
        logger.info(f'Backup created: {dest}')
        return {'name': name}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_palworld_service.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/service/palworld_service.py suh-ai-server/flask/test/test_palworld_service.py
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : PalworldService 서비스 제어·REST 중계·백업 구현 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

### Task 5: palworld_router REST API (TDD)

**Files:**
- Create: `suh-ai-server/flask/router/palworld_router.py`
- Test: `suh-ai-server/flask/test/test_palworld_router.py`

**Interfaces:**
- Consumes: `PalworldService`, `ServerRunningError` (Task 4 시그니처 그대로)
- Produces: Blueprint `palworld_bp` — `GET /palworld/status`, `POST /palworld/start|stop|restart`, `GET|PUT /palworld/settings`, `GET /palworld/logs`, `GET|POST /palworld/backups`. Task 7에서 app.py에 등록. 프론트 JS(Task 6)가 이 응답 스키마에 의존.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""test_palworld_router.py"""
import pytest
from unittest.mock import patch
from flask import Flask
from service.palworld_service import ServerRunningError


@pytest.fixture
def client():
    from router.palworld_router import palworld_bp
    app = Flask(__name__)
    app.register_blueprint(palworld_bp)
    return app.test_client()


def test_status_returns_service_result(client):
    fake = {'state': 'running', 'rest_available': True, 'info': {}, 'players': [], 'metrics': {}}
    with patch('router.palworld_router.palworld_service.get_status', return_value=fake):
        resp = client.get('/palworld/status')
    assert resp.status_code == 200
    assert resp.get_json()['state'] == 'running'


def test_start_success(client):
    with patch('router.palworld_router.palworld_service.start'):
        resp = client.post('/palworld/start')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_start_failure_returns_500(client):
    with patch('router.palworld_router.palworld_service.start', side_effect=RuntimeError('boom')):
        resp = client.post('/palworld/start')
    assert resp.status_code == 500


def test_put_settings_while_running_returns_409(client):
    with patch('router.palworld_router.palworld_service.update_settings',
               side_effect=ServerRunningError('running')):
        resp = client.put('/palworld/settings', json={'ServerName': 'X'})
    assert resp.status_code == 409


def test_put_settings_requires_json(client):
    resp = client.put('/palworld/settings', data='not json', content_type='text/plain')
    assert resp.status_code == 400


def test_create_backup(client):
    with patch('router.palworld_router.palworld_service.create_backup', return_value={'name': '20260713_120000'}):
        resp = client.post('/palworld/backups')
    assert resp.status_code == 200
    assert resp.get_json()['name'] == '20260713_120000'
```

- [ ] **Step 2: 실패 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/test_palworld_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'router.palworld_router'`

- [ ] **Step 3: 구현**

```python
"""
Palworld server management router
"""
from flask import Blueprint, request, jsonify
from service.palworld_service import PalworldService, ServerRunningError
import logging

logger = logging.getLogger(__name__)

palworld_bp = Blueprint('palworld', __name__)
palworld_service = PalworldService()


@palworld_bp.route('/palworld/status', methods=['GET'])
def status():
    """서버 상태 + 접속자 + 메트릭 통합 조회"""
    try:
        return jsonify(palworld_service.get_status()), 200
    except Exception as e:
        logger.error(f"Status error: {str(e)}")
        return jsonify({'error': str(e)}), 500


def _control(action_name):
    try:
        getattr(palworld_service, action_name)()
        return jsonify({'success': True, 'action': action_name}), 200
    except Exception as e:
        logger.error(f"{action_name} error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@palworld_bp.route('/palworld/start', methods=['POST'])
def start():
    """서버 시작"""
    return _control('start')


@palworld_bp.route('/palworld/stop', methods=['POST'])
def stop():
    """서버 중지"""
    return _control('stop')


@palworld_bp.route('/palworld/restart', methods=['POST'])
def restart():
    """서버 재시작"""
    return _control('restart')


@palworld_bp.route('/palworld/settings', methods=['GET'])
def get_settings():
    """PalWorldSettings.ini 조회"""
    try:
        return jsonify(palworld_service.get_settings()), 200
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Settings read error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/settings', methods=['PUT'])
def put_settings():
    """PalWorldSettings.ini 수정 (서버 가동 중이면 409)"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'JSON body required'}), 400
    try:
        return jsonify(palworld_service.update_settings(data)), 200
    except ServerRunningError as e:
        return jsonify({'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Settings write error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/logs', methods=['GET'])
def logs():
    """서버 로그 tail"""
    try:
        lines = int(request.args.get('lines', 200))
        return jsonify({'logs': palworld_service.tail_logs(lines)}), 200
    except Exception as e:
        logger.error(f"Log read error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/backups', methods=['GET'])
def list_backups():
    """백업 목록"""
    try:
        return jsonify({'backups': palworld_service.list_backups()}), 200
    except Exception as e:
        logger.error(f"Backup list error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@palworld_bp.route('/palworld/backups', methods=['POST'])
def create_backup():
    """즉시 백업 실행"""
    try:
        return jsonify(palworld_service.create_backup()), 200
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Backup create error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/ -v`
Expected: 전체 통과 (ini 7 + service 9 + router 6 = 22 passed)

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/router/palworld_router.py suh-ai-server/flask/test/test_palworld_router.py
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : palworld REST API 라우터 구현 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

### Task 6: 프론트엔드 — DaisyUI 빌드 환경 + 대시보드 + 팰월드 페이지

**Files:**
- Create: `suh-ai-server/flask/frontend/package.json`
- Create: `suh-ai-server/flask/frontend/input.css`
- Create: `suh-ai-server/flask/frontend/.gitignore` (node_modules)
- Create: `suh-ai-server/flask/router/admin_router.py`
- Create: `suh-ai-server/flask/templates/admin/dashboard.html`
- Create: `suh-ai-server/flask/templates/admin/palworld.html`
- Create: `suh-ai-server/flask/static/js/admin-common.js`
- Create: `suh-ai-server/flask/static/js/palworld.js`
- Create: `suh-ai-server/flask/static/css/app.css` (빌드 산출물 — 커밋 포함)

**Interfaces:**
- Consumes: Task 5의 `/palworld/*` API 응답 스키마
- Produces: Blueprint `admin_bp` — `GET /admin`(dashboard), `GET /admin/palworld`. `window.apiFetch(path, options)` 전역 함수 (admin-common.js)

- [ ] **Step 1: admin_router.py 작성**

```python
"""
Admin pages router - DaisyUI 관리자 페이지 렌더링
"""
from flask import Blueprint, render_template

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin', methods=['GET'])
def dashboard():
    """관리 허브 대시보드"""
    return render_template('admin/dashboard.html')


@admin_bp.route('/admin/palworld', methods=['GET'])
def palworld():
    """팰월드 서버 관리 페이지"""
    return render_template('admin/palworld.html')
```

- [ ] **Step 2: frontend 빌드 환경 작성**

`frontend/package.json`:
```json
{
  "name": "suh-ai-admin-frontend",
  "private": true,
  "scripts": {
    "build": "tailwindcss -i input.css -o ../static/css/app.css --minify"
  },
  "devDependencies": {
    "@tailwindcss/cli": "^4.1.0",
    "tailwindcss": "^4.1.0",
    "daisyui": "^5.0.0"
  }
}
```

`frontend/input.css`:
```css
@import "tailwindcss";
@plugin "daisyui";
@source "../templates/**/*.html";
@source "../static/js/*.js";
```

`frontend/.gitignore`:
```
node_modules/
```

- [ ] **Step 3: admin-common.js 작성** (API Key modal + fetch 래퍼 — 모든 URL 상대경로)

```javascript
/* API Key 관리 + 인증 fetch 래퍼. nginx가 X-API-Key를 검증한다. */
(function () {
  const KEY_STORAGE = 'suh_admin_api_key';

  function getApiKey() {
    return localStorage.getItem(KEY_STORAGE) || '';
  }

  function showKeyModal() {
    document.getElementById('api-key-modal').showModal();
  }

  window.saveApiKey = function () {
    const input = document.getElementById('api-key-input');
    if (input.value.trim()) {
      localStorage.setItem(KEY_STORAGE, input.value.trim());
      document.getElementById('api-key-modal').close();
      window.location.reload();
    }
  };

  window.resetApiKey = function () {
    localStorage.removeItem(KEY_STORAGE);
    showKeyModal();
  };

  /* 상대경로 전용 fetch — 401이면 키 재입력 modal */
  window.apiFetch = async function (path, options = {}) {
    const headers = Object.assign({}, options.headers, {
      'X-API-Key': getApiKey(),
      'Content-Type': 'application/json',
    });
    const resp = await fetch(path, Object.assign({}, options, { headers }));
    if (resp.status === 401) {
      showKeyModal();
      throw new Error('Unauthorized - API Key required');
    }
    return resp;
  };

  window.showToast = function (message, type = 'info') {
    const toast = document.getElementById('toast-container');
    const alert = document.createElement('div');
    alert.className = 'alert alert-' + type;
    alert.innerHTML = '<span>' + message + '</span>';
    toast.appendChild(alert);
    setTimeout(() => alert.remove(), 4000);
  };

  document.addEventListener('DOMContentLoaded', function () {
    if (!getApiKey()) showKeyModal();
  });
})();
```

- [ ] **Step 4: dashboard.html 작성**

```html
<!DOCTYPE html>
<html lang="ko" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SUH AI Server Admin</title>
  <link rel="stylesheet" href="../static/css/app.css">
</head>
<body class="min-h-screen bg-base-200">
  <div class="navbar bg-base-100 shadow">
    <div class="flex-1"><span class="text-xl font-bold px-4">🖥 SUH AI Server Admin</span></div>
    <div class="flex-none px-4">
      <button class="btn btn-ghost btn-sm" onclick="resetApiKey()">🔑 API Key</button>
    </div>
  </div>

  <main class="container mx-auto p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
    <a href="./admin/palworld" class="card bg-base-100 shadow-md hover:shadow-xl transition-shadow">
      <div class="card-body">
        <h2 class="card-title">🎮 팰월드 서버 관리
          <span id="pal-badge" class="badge badge-ghost">확인중…</span>
        </h2>
        <p>서버 시작/중지, 설정, 로그, 백업 관리</p>
      </div>
    </a>
    <a href="./docs/swagger" class="card bg-base-100 shadow-md hover:shadow-xl transition-shadow">
      <div class="card-body">
        <h2 class="card-title">📄 OCR API</h2>
        <p>Swagger 문서로 이동</p>
      </div>
    </a>
    <a href="./docs/swagger" class="card bg-base-100 shadow-md hover:shadow-xl transition-shadow">
      <div class="card-body">
        <h2 class="card-title">👁 Vision API</h2>
        <p>Swagger 문서로 이동</p>
      </div>
    </a>
    <div class="card bg-base-100 shadow-md">
      <div class="card-body">
        <h2 class="card-title">📋 Flask 서버 로그</h2>
        <pre id="flask-logs" class="mockup-code text-xs overflow-x-auto max-h-48 p-4">불러오는 중…</pre>
      </div>
    </div>
  </main>

  <dialog id="api-key-modal" class="modal">
    <div class="modal-box">
      <h3 class="font-bold text-lg">🔑 API Key 입력</h3>
      <p class="py-2 text-sm">nginx 인증용 X-API-Key를 입력하세요. 브라우저에 저장됩니다.</p>
      <input id="api-key-input" type="password" class="input input-bordered w-full" placeholder="API Key">
      <div class="modal-action">
        <button class="btn btn-primary" onclick="saveApiKey()">저장</button>
      </div>
    </div>
  </dialog>
  <div id="toast-container" class="toast toast-end"></div>

  <script src="../static/js/admin-common.js"></script>
  <script>
    document.addEventListener('DOMContentLoaded', async function () {
      try {
        const resp = await apiFetch('./palworld/status');
        const data = await resp.json();
        const badge = document.getElementById('pal-badge');
        badge.textContent = data.state === 'running' ? 'RUNNING' : data.state.toUpperCase();
        badge.className = 'badge ' + (data.state === 'running' ? 'badge-success' : 'badge-error');
      } catch (e) { /* 401 modal은 apiFetch가 처리 */ }
      try {
        const resp = await apiFetch('./logs?lines=30');
        const data = await resp.json();
        document.getElementById('flask-logs').textContent = (data.logs || []).join('\n') || '(로그 없음)';
      } catch (e) { /* ignore */ }
    });
  </script>
</body>
</html>
```

> 주의: `/admin` 경로 기준 상대 URL이므로 `./admin/palworld`가 아니라 위처럼 작성하면 `/admin/palworld`가 아닌 `/admin/admin/palworld`가 될 수 있다. `/admin`(트레일링 슬래시 없음)의 base는 `/`이므로 `./admin/palworld` → `/admin/palworld`, `../static/...` → `/static/...`? 아니다 — base가 `/`이면 `../static`도 `/static`이다. 외부(`/api/flask/admin`)에서는 base가 `/api/flask/`이므로 `./admin/palworld` → `/api/flask/admin/palworld`, `../static` → `/static`(prefix 이탈!). **따라서 dashboard.html의 static 참조는 `./static/css/app.css`, `./static/js/admin-common.js`로 작성한다** (base 디렉토리 기준 → 로컬 `/static/...`, 외부 `/api/flask/static/...` 모두 정상). palworld.html은 `/admin/palworld` 기준이므로 base 디렉토리가 한 단계 깊어 `../static/...`, API는 `../palworld/status`가 맞다. 구현 시 이 규칙대로 dashboard.html의 `../static/` 두 곳을 `./static/`으로 바꿔 작성할 것.

- [ ] **Step 5: palworld.html 작성**

```html
<!DOCTYPE html>
<html lang="ko" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>팰월드 서버 관리</title>
  <link rel="stylesheet" href="../static/css/app.css">
</head>
<body class="min-h-screen bg-base-200">
  <div class="navbar bg-base-100 shadow">
    <div class="flex-1">
      <a href="../admin" class="btn btn-ghost">← 대시보드</a>
      <span class="text-xl font-bold px-2">🎮 팰월드 서버</span>
      <span id="state-badge" class="badge badge-ghost">확인중…</span>
    </div>
    <div class="flex-none gap-2 px-4">
      <button id="btn-start" class="btn btn-success btn-sm" onclick="controlServer('start')">시작</button>
      <button id="btn-stop" class="btn btn-error btn-sm" onclick="controlServer('stop')">중지</button>
      <button id="btn-restart" class="btn btn-warning btn-sm" onclick="controlServer('restart')">재시작</button>
    </div>
  </div>

  <main class="container mx-auto p-6 space-y-6">
    <div class="stats shadow w-full bg-base-100">
      <div class="stat">
        <div class="stat-title">접속자</div>
        <div id="stat-players" class="stat-value">-</div>
        <div id="stat-maxplayers" class="stat-desc">/ - 명</div>
      </div>
      <div class="stat">
        <div class="stat-title">서버 FPS</div>
        <div id="stat-fps" class="stat-value">-</div>
      </div>
      <div class="stat">
        <div class="stat-title">업타임</div>
        <div id="stat-uptime" class="stat-value text-2xl">-</div>
      </div>
    </div>

    <div role="tablist" class="tabs tabs-lifted">
      <input type="radio" name="main_tabs" role="tab" class="tab" aria-label="⚙️ 설정" checked>
      <div role="tabpanel" class="tab-content bg-base-100 border-base-300 rounded-box p-6">
        <div class="alert alert-warning mb-4 text-sm">
          <span>⚠️ 설정 저장은 서버가 <b>중지 상태</b>일 때만 가능합니다. (가동 중 저장 시 종료 시점에 덮어씌워져 유실)</span>
        </div>
        <div id="settings-form" class="space-y-2"></div>
        <div class="mt-4 flex gap-2">
          <button class="btn btn-primary" onclick="saveSettings()">저장</button>
          <button class="btn btn-secondary" onclick="stopSaveRestart()">중지 → 저장 → 재시작</button>
        </div>
      </div>

      <input type="radio" name="main_tabs" role="tab" class="tab" aria-label="📋 로그">
      <div role="tabpanel" class="tab-content bg-base-100 border-base-300 rounded-box p-6">
        <pre id="log-view" class="mockup-code text-xs overflow-x-auto max-h-96 p-4">불러오는 중…</pre>
      </div>

      <input type="radio" name="main_tabs" role="tab" class="tab" aria-label="💾 백업">
      <div role="tabpanel" class="tab-content bg-base-100 border-base-300 rounded-box p-6">
        <button class="btn btn-primary mb-4" onclick="createBackup()">지금 백업</button>
        <div class="overflow-x-auto">
          <table class="table table-zebra">
            <thead><tr><th>이름</th><th>크기(MB)</th><th>생성 시각</th></tr></thead>
            <tbody id="backup-list"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="card bg-base-100 shadow">
      <div class="card-body">
        <h2 class="card-title text-base">👥 접속 중인 플레이어</h2>
        <div class="overflow-x-auto">
          <table class="table table-sm">
            <thead><tr><th>이름</th><th>레벨</th><th>Ping</th></tr></thead>
            <tbody id="player-list"><tr><td colspan="3">-</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>
  </main>

  <dialog id="api-key-modal" class="modal">
    <div class="modal-box">
      <h3 class="font-bold text-lg">🔑 API Key 입력</h3>
      <p class="py-2 text-sm">nginx 인증용 X-API-Key를 입력하세요. 브라우저에 저장됩니다.</p>
      <input id="api-key-input" type="password" class="input input-bordered w-full" placeholder="API Key">
      <div class="modal-action">
        <button class="btn btn-primary" onclick="saveApiKey()">저장</button>
      </div>
    </div>
  </dialog>
  <div id="toast-container" class="toast toast-end"></div>

  <script src="../static/js/admin-common.js"></script>
  <script src="../static/js/palworld.js"></script>
</body>
</html>
```

- [ ] **Step 6: palworld.js 작성**

```javascript
/* 팰월드 관리 페이지 로직. base: /admin/palworld → API는 ../palworld/* */
const API = '../palworld';
let currentState = 'unknown';

async function refreshStatus() {
  try {
    const resp = await apiFetch(API + '/status');
    const data = await resp.json();
    currentState = data.state;
    const badge = document.getElementById('state-badge');
    badge.textContent = data.state.toUpperCase();
    badge.className = 'badge ' + (data.state === 'running' ? 'badge-success' : 'badge-error');

    if (data.rest_available && data.metrics) {
      document.getElementById('stat-players').textContent = data.metrics.currentplayernum;
      document.getElementById('stat-maxplayers').textContent = '/ ' + data.metrics.maxplayernum + ' 명';
      document.getElementById('stat-fps').textContent = data.metrics.serverfps;
      document.getElementById('stat-uptime').textContent = formatUptime(data.metrics.uptime);
    } else {
      ['stat-players', 'stat-fps', 'stat-uptime'].forEach(id =>
        document.getElementById(id).textContent = '-');
    }

    const tbody = document.getElementById('player-list');
    if (data.players && data.players.length) {
      tbody.innerHTML = data.players.map(p =>
        '<tr><td>' + p.name + '</td><td>' + p.level + '</td><td>' + Math.round(p.ping) + 'ms</td></tr>'
      ).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="3">접속자 없음</td></tr>';
    }
  } catch (e) { /* 401은 modal 처리 */ }
}

function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
  return h + 'h ' + m + 'm';
}

async function controlServer(action) {
  if (!confirm('서버를 ' + action + ' 하시겠습니까?')) return;
  try {
    const resp = await apiFetch(API + '/' + action, { method: 'POST' });
    const data = await resp.json();
    if (data.success) showToast(action + ' 완료', 'success');
    else showToast(data.error || action + ' 실패', 'error');
  } catch (e) {
    showToast(String(e), 'error');
  }
  setTimeout(refreshStatus, 2000);
}

async function loadSettings() {
  try {
    const resp = await apiFetch(API + '/settings');
    const data = await resp.json();
    const form = document.getElementById('settings-form');
    form.innerHTML = data.editable_keys.map(key => {
      const raw = data.settings[key] || '';
      const value = raw.replace(/^"|"$/g, '');
      const isBool = raw === 'True' || raw === 'False';
      if (isBool) {
        return '<label class="label cursor-pointer justify-start gap-4"><span class="label-text w-56">' + key +
          '</span><input type="checkbox" class="toggle toggle-primary" data-key="' + key + '"' +
          (raw === 'True' ? ' checked' : '') + '></label>';
      }
      return '<label class="label justify-start gap-4"><span class="label-text w-56">' + key +
        '</span><input type="text" class="input input-bordered input-sm w-64" data-key="' + key +
        '" value="' + value.replace(/"/g, '&quot;') + '"></label>';
    }).join('');
  } catch (e) { /* ignore */ }
}

function collectChanges() {
  const changes = {};
  document.querySelectorAll('#settings-form [data-key]').forEach(el => {
    changes[el.dataset.key] = el.type === 'checkbox' ? (el.checked ? 'True' : 'False') : el.value;
  });
  return changes;
}

async function saveSettings() {
  try {
    const resp = await apiFetch(API + '/settings', {
      method: 'PUT', body: JSON.stringify(collectChanges()),
    });
    if (resp.status === 409) {
      showToast('서버 가동 중에는 저장할 수 없습니다. 먼저 중지하세요.', 'warning');
      return;
    }
    if (resp.ok) showToast('설정 저장 완료', 'success');
    else showToast((await resp.json()).error || '저장 실패', 'error');
  } catch (e) { showToast(String(e), 'error'); }
}

async function stopSaveRestart() {
  if (!confirm('서버를 중지하고 설정 저장 후 재시작합니다. 진행할까요?')) return;
  try {
    await apiFetch(API + '/stop', { method: 'POST' });
    showToast('서버 중지 완료, 설정 저장 중…', 'info');
    const resp = await apiFetch(API + '/settings', {
      method: 'PUT', body: JSON.stringify(collectChanges()),
    });
    if (!resp.ok) {
      showToast('설정 저장 실패: ' + (await resp.json()).error, 'error');
      return;
    }
    await apiFetch(API + '/start', { method: 'POST' });
    showToast('설정 저장 후 서버 재시작 완료', 'success');
  } catch (e) { showToast(String(e), 'error'); }
  setTimeout(refreshStatus, 2000);
}

async function refreshLogs() {
  try {
    const resp = await apiFetch(API + '/logs?lines=200');
    const data = await resp.json();
    const view = document.getElementById('log-view');
    view.textContent = (data.logs || []).join('\n') || '(로그 없음)';
    view.scrollTop = view.scrollHeight;
  } catch (e) { /* ignore */ }
}

async function loadBackups() {
  try {
    const resp = await apiFetch(API + '/backups');
    const data = await resp.json();
    document.getElementById('backup-list').innerHTML = (data.backups || []).map(b =>
      '<tr><td>' + b.name + '</td><td>' + b.size_mb + '</td><td>' + b.created + '</td></tr>'
    ).join('') || '<tr><td colspan="3">백업 없음</td></tr>';
  } catch (e) { /* ignore */ }
}

async function createBackup() {
  try {
    const resp = await apiFetch(API + '/backups', { method: 'POST' });
    if (resp.ok) {
      showToast('백업 완료: ' + (await resp.json()).name, 'success');
      loadBackups();
    } else {
      showToast((await resp.json()).error || '백업 실패', 'error');
    }
  } catch (e) { showToast(String(e), 'error'); }
}

document.addEventListener('DOMContentLoaded', function () {
  refreshStatus();
  loadSettings();
  refreshLogs();
  loadBackups();
  setInterval(refreshStatus, 5000);
  setInterval(refreshLogs, 10000);
});
```

- [ ] **Step 7: CSS 빌드**

Run: `cd suh-ai-server/flask/frontend && npm install && npm run build`
Expected: `../static/css/app.css` 생성, 콘솔에 `Done in Xms`

- [ ] **Step 8: Commit**

```bash
git add suh-ai-server/flask/frontend suh-ai-server/flask/router/admin_router.py suh-ai-server/flask/templates suh-ai-server/flask/static
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : DaisyUI 대시보드 및 팰월드 관리 페이지 구현 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

### Task 7: app.py 등록 + Swagger 스펙 추가

**Files:**
- Create: `suh-ai-server/flask/router/palworld_swagger.py`
- Modify: `suh-ai-server/flask/app.py` (blueprint 등록 2줄 추가)
- Modify: `suh-ai-server/flask/router/swagger_router.py:398` (paths merge 1줄)

**Interfaces:**
- Consumes: `palworld_bp`, `admin_bp`
- Produces: Swagger UI에 Palworld 태그 API 문서 노출

- [ ] **Step 1: palworld_swagger.py 작성**

```python
"""
Palworld API Swagger paths (swagger_router에서 merge)
"""

PALWORLD_SWAGGER_PATHS = {
    "/palworld/status": {
        "get": {
            "tags": ["Palworld"],
            "summary": "서버 상태 조회 (서비스 상태 + 접속자 + 메트릭)",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "상태 조회 성공"}, "500": {"description": "서버 오류"}}
        }
    },
    "/palworld/start": {
        "post": {
            "tags": ["Palworld"], "summary": "서버 시작",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "시작 성공"}, "500": {"description": "시작 실패"}}
        }
    },
    "/palworld/stop": {
        "post": {
            "tags": ["Palworld"], "summary": "서버 중지",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "중지 성공"}, "500": {"description": "중지 실패"}}
        }
    },
    "/palworld/restart": {
        "post": {
            "tags": ["Palworld"], "summary": "서버 재시작",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "재시작 성공"}, "500": {"description": "재시작 실패"}}
        }
    },
    "/palworld/settings": {
        "get": {
            "tags": ["Palworld"], "summary": "PalWorldSettings.ini 조회",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "조회 성공"}, "404": {"description": "ini 파일 없음"}}
        },
        "put": {
            "tags": ["Palworld"], "summary": "PalWorldSettings.ini 수정 (서버 정지 상태에서만)",
            "security": [{"ApiKeyAuth": []}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "example": {"ServerName": "팰 사냥터", "ExpRate": "2.0", "bCrossplay": "True"}
                }}}
            },
            "responses": {
                "200": {"description": "수정 성공"},
                "400": {"description": "잘못된 요청"},
                "409": {"description": "서버 가동 중 - 중지 후 수정 필요"}
            }
        }
    },
    "/palworld/logs": {
        "get": {
            "tags": ["Palworld"], "summary": "서버 로그 tail",
            "security": [{"ApiKeyAuth": []}],
            "parameters": [{
                "name": "lines", "in": "query",
                "schema": {"type": "integer", "default": 200, "maximum": 500}
            }],
            "responses": {"200": {"description": "로그 조회 성공"}}
        }
    },
    "/palworld/backups": {
        "get": {
            "tags": ["Palworld"], "summary": "백업 목록 조회",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "목록 조회 성공"}}
        },
        "post": {
            "tags": ["Palworld"], "summary": "즉시 백업 실행",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "백업 성공"}, "404": {"description": "SaveGames 폴더 없음"}}
        }
    }
}
```

- [ ] **Step 2: swagger_router.py 수정** — import 추가 및 `return jsonify(swagger_spec), 200` 직전에 merge

```python
# 파일 상단 import에 추가:
from router.palworld_swagger import PALWORLD_SWAGGER_PATHS

# swagger_json() 함수 끝의 return 직전에 추가:
    swagger_spec["paths"].update(PALWORLD_SWAGGER_PATHS)
    return jsonify(swagger_spec), 200
```

- [ ] **Step 3: app.py 수정** — 기존 blueprint 등록부에 추가

```python
# import 추가:
from router.palworld_router import palworld_bp
from router.admin_router import admin_bp

# Register routers 블록에 추가:
app.register_blueprint(palworld_bp)
app.register_blueprint(admin_bp)
```

- [ ] **Step 4: 전체 테스트 + 앱 기동 확인**

Run: `cd suh-ai-server/flask && python -m pytest test/ -v && python -c "from app import app; print([r.rule for r in app.url_map.iter_rules() if 'palworld' in r.rule or 'admin' in r.rule])"`
Expected: 22 passed, `/palworld/status`, `/admin`, `/admin/palworld` 등 라우트 출력

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/app.py suh-ai-server/flask/router/swagger_router.py suh-ai-server/flask/router/palworld_swagger.py
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : blueprint 등록 및 Swagger 스펙 추가 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

### Task 8: nginx public 규칙 + 로컬 검증 + 배포

**Files:**
- Modify: `suh-ai-server/config/nginx.conf:36-42` (public map)

**Interfaces:**
- Consumes: 완성된 Flask 앱 전체
- Produces: 외부에서 `https://ai.suhsaechan.kr/api/flask/admin` 접속 가능

- [ ] **Step 1: nginx.conf public 엔드포인트 map에 추가**

```nginx
    # Public endpoints that don't require authentication
    map $request_uri $is_public_endpoint {
        default 0;
        ~^/health$ 1;                      # Ollama health endpoint
        ~^/api/tags$ 1;                    # Ollama tags endpoint (GET only, no auth required)
        ~^/api/flask/docs/swagger 1;       # Flask Swagger UI
        ~^/docs/swagger 1;                 # Short URL for Swagger UI
        ~^/api/flask/admin 1;              # Admin pages (API는 여전히 키 필수)
        ~^/api/flask/static/ 1;            # Admin static assets (css/js)
    }
```

- [ ] **Step 2: 로컬 Flask 개발 모드로 브라우저 검증**

Run: `cd suh-ai-server/flask && python app.py` (별도 백그라운드), 브라우저에서 `http://localhost:5000/admin` 접속
Expected: 대시보드 렌더, API Key modal 표시, 팰월드 카드 → `/admin/palworld` 이동, 상태 badge RUNNING (Task 1에서 서버 가동 중이므로). 확인 후 dev 서버 종료.
주의: 로컬 직접 접속은 nginx를 안 거치므로 401이 없다 — modal에 아무 값이나 넣으면 동작.

- [ ] **Step 3: 운영 반영**

로컬 nginx 배포 스크립트 실행(`suh-ai-server/scripts/deploy-nginx.ps1` — API 키 목록 주입 방식 확인 후) 또는 기존 CI 파이프라인으로 배포. Flask는 `deploy-flask.ps1` 실행으로 `FlaskOCRService` 재시작.
Expected: `https://ai.suhsaechan.kr/api/flask/admin` 접속 시 대시보드 표시, API Key 입력 후 팰월드 상태 조회 성공

- [ ] **Step 4: Commit + 이슈 코멘트**

```bash
git add suh-ai-server/config/nginx.conf
git commit -m "Palworld 데디케이티드 서버 구축 및 DaisyUI 관리자 페이지 : feat : admin 페이지 nginx public 규칙 추가 https://github.com/Cassiiopeia/suh-project-control/issues/46"
```

---

## 수동 작업 (사용자 — 코드와 무관, 아무 때나)

- 공유기(`http://172.30.1.254`) 접속 → 포트포워딩 UDP 8211 → 172.30.1.14 추가 (DMZ 유지)
- (선택) UDP 27015 → 172.30.1.14
- DHCP 고정 할당: Windows PC MAC → 172.30.1.14
- 외부 검증: 친구가 `suh-project.synology.me:8211`로 게임 접속

## Self-Review 결과

- 스펙 커버리지: 설계 문서의 아키텍처(NSSM/REST/인증), 페이지 구조(대시보드+팰월드), API 9종, ini 가드(409), 백업, nginx, 설치 스크립트 모두 태스크에 매핑됨
- 상대경로 함정: dashboard.html(`/admin` base → `./static/`)과 palworld.html(`/admin/palworld` base → `../static/`)의 차이를 Task 6 Step 4 주의사항에 명시
- 타입 일관성: `ServerRunningError`, `palworld_service` 인스턴스명, API 응답 키(`state`, `rest_available`, `settings`, `editable_keys`, `backups`)가 서비스→라우터→JS에서 동일하게 사용됨을 확인
