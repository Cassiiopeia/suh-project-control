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
    "CrossplayPlatforms", "ExpRate", "PalCaptureRate", "DeathPenalty",
    "bEnablePlayerToPlayerDamage", "DayTimeSpeedRate", "NightTimeSpeedRate",
    "PalSpawnNumRate", "CollectionDropRate", "WorkSpeedRate",
]
