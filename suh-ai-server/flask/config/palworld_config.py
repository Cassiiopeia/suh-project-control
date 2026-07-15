"""
Palworld server management configuration
"""
import os

PALWORLD_BASE_DIR = r"C:\AI\palworld"
PALSERVER_DIR = os.path.join(PALWORLD_BASE_DIR, "steamcmd", "steamapps", "common", "PalServer")
INI_PATH = os.path.join(PALSERVER_DIR, "Pal", "Saved", "Config", "WindowsServer", "PalWorldSettings.ini")
SAVE_DIR = os.path.join(PALSERVER_DIR, "Pal", "Saved", "SaveGames")
BACKUP_DIR = os.path.join(PALWORLD_BASE_DIR, "backups")

# 로그 소스: 팰월드 로그 탭에서 선택 조회하는 파일들
# events  = Flask 폴러가 자체 생성하는 접속/퇴장 이벤트 (JSON Lines)
# game    = 엔진의 진짜 서버 로그. Palworld 데디(Pocket Pair 빌드)는 UE 파일 로그를
#           꺼서 배포하므로 Pal/Saved/Logs/Pal.log는 생성되지 않는다(-log/-abslog 미동작).
#           엔진 출력은 stdout으로만 나가고 NSSM이 palserver-stdout.log로 캡처하므로,
#           "게임 로그"는 이 캡처 파일을 가리킨다.
# stderr  = NSSM 표준에러 리다이렉트 (크래시·프로세스 단서)
# flask   = Flask 앱(관리자 서버) 자체 로그 — 관리자 시스템 로그 조회용
_PAL_STDOUT = os.path.join(PALWORLD_BASE_DIR, "logs", "palserver-stdout.log")
LOG_SOURCES = {
    "events": os.path.join(PALWORLD_BASE_DIR, "logs", "palworld-events.jsonl"),
    "game":   _PAL_STDOUT,
    "stdout": _PAL_STDOUT,
    "stderr": os.path.join(PALWORLD_BASE_DIR, "logs", "palserver-stderr.log"),
    "flask":  os.path.join(r"C:\AI\suh-ai-server", "flask", "logs", "nssm-stderr.log"),
}

# 메트릭 시계열 히스토리 (FPS·접속자·프레임타임 추이 그래프용).
# 서버 REST는 순간값만 주므로 폴러가 주기적으로 스냅샷을 이 파일에 적재한다.
METRICS_HISTORY_FILE = os.path.join(PALWORLD_BASE_DIR, "logs", "palworld-metrics.jsonl")
METRICS_HISTORY_MAXLEN = 720          # 링버퍼 길이 (10초 간격 × 720 = 약 2시간)
METRICS_HISTORY_MAX_BYTES = 5 * 1024 * 1024

# 게임 접속 가이드에 표시할 공개 주소
PUBLIC_HOST = "suh-project.synology.me"
PUBLIC_PORT = 8211

SERVICE_NAME = "PalServer"
REST_BASE_URL = "http://127.0.0.1:8212"

# NSSM 서비스가 PalServer-Win64-Shipping-Cmd.exe에 넘겨야 하는 실행 인자(정본).
# -log: 언리얼 엔진이 Pal\Saved\Logs\Pal.log를 디스크에 기록하도록 강제한다.
#       이 플래그가 없으면 게임 로그 파일이 아예 생성되지 않는다.
# setup-palworld.ps1과 이 값이 일치해야 하며, Flask(SYSTEM 권한)가 서버 시작/재시작 시
# NSSM AppParameters에 -log가 빠져 있으면 이 값으로 자가 치유한다.
PALSERVER_ARGS = "-port=8211 -players=32 -log -useperfthreads -NoAsyncLoadingThread -UseMultithreadForDS"
REQUIRED_ARG_FLAG = "-log"
NSSM_PATH = r"C:\ProgramData\chocolatey\bin\nssm.exe"

# OptionSettings에서 문자열로 취급해 따옴표를 붙여야 하는 키
STRING_KEYS = {
    "ServerName", "ServerDescription", "AdminPassword", "ServerPassword",
    "PublicIP", "Region", "BanListURL", "LogFormatType",
}

# 관리자 페이지에서 편집 허용하는 키 (그 외 키는 PUT 시 무시)
EDITABLE_KEYS = [
    "ServerName", "ServerDescription", "ServerPassword", "ServerPlayerMaxNum",
    "CrossplayPlatforms", "ExpRate", "PalCaptureRate", "DeathPenalty",
    "bEnablePlayerToPlayerDamage", "DayTimeSpeedRate", "NightTimeSpeedRate",
    "PalSpawnNumRate", "CollectionDropRate", "WorkSpeedRate",
]

# 서버 바이너리 업데이트 (SteamCMD)
STEAMCMD_EXE = os.path.join(PALWORLD_BASE_DIR, "steamcmd", "steamcmd.exe")
PALWORLD_APP_ID = "2394010"
APP_MANIFEST_PATH = os.path.join(PALWORLD_BASE_DIR, "steamcmd", "steamapps",
                                 f"appmanifest_{PALWORLD_APP_ID}.acf")
UPDATE_CHECK_INTERVAL_SEC = 1800   # 새 빌드 자동 감지 주기 (30분)
UPDATE_LOG_MAXLEN = 300            # 업데이트 진행 로그 링버퍼
UPDATE_TIMEOUT_SEC = 3600          # steamcmd 무응답 워치독 — 초과 시 강제 종료
