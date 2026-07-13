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
