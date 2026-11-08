"""
Logging configuration
"""
import logging
import os
from logging.handlers import RotatingFileHandler

# 파일 로그 1개 최대 크기 (10MB) — scripts/deploy-flask.ps1 NSSM AppRotateBytes 와 같은 값
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
# 로테이션 백업 파일 개수 (flask_ocr.log.1 ~ .5) → 총 최대 약 60MB
LOG_FILE_BACKUP_COUNT = 5


def create_rotating_file_handler(log_file_path: str,
                                 max_bytes: int = LOG_FILE_MAX_BYTES,
                                 backup_count: int = LOG_FILE_BACKUP_COUNT) -> RotatingFileHandler:
    """크기 초과 시 회전하는 파일 핸들러 (한글 로그 때문에 UTF-8 고정)"""
    return RotatingFileHandler(log_file_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')


def setup_logging():
    """
    Setup logging configuration

    Returns:
        Logger instance
    """
    # Create logs directory if not exists
    logs_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    return logging.getLogger(__name__)
