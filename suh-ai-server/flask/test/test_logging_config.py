"""test_logging_config.py"""
import logging
from logging.handlers import RotatingFileHandler

from config.logging_config import (
    LOG_FILE_BACKUP_COUNT, LOG_FILE_MAX_BYTES, create_rotating_file_handler,
)


def test_handler_rotates_by_size_with_limited_backups(tmp_path):
    handler = create_rotating_file_handler(str(tmp_path / 'flask_ocr.log'))
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == LOG_FILE_MAX_BYTES == 10 * 1024 * 1024
        assert handler.backupCount == LOG_FILE_BACKUP_COUNT == 5
    finally:
        handler.close()


def test_handler_keeps_korean_text_readable(tmp_path):
    log_path = tmp_path / 'flask_ocr.log'
    handler = create_rotating_file_handler(str(log_path))
    logger = logging.getLogger('test_logging_config_korean')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info('서버 시작')
    finally:
        logger.removeHandler(handler)
        handler.close()
    assert '서버 시작' in log_path.read_text(encoding='utf-8')


def test_handler_rolls_over_when_size_exceeded(tmp_path):
    log_path = tmp_path / 'flask_ocr.log'
    handler = create_rotating_file_handler(str(log_path), max_bytes=200, backup_count=2)
    logger = logging.getLogger('test_logging_config_rollover')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        for _ in range(30):
            logger.info('x' * 50)
    finally:
        logger.removeHandler(handler)
        handler.close()
    # 백업은 지정한 개수까지만 남는다
    assert (tmp_path / 'flask_ocr.log.1').exists()
    assert not (tmp_path / 'flask_ocr.log.3').exists()
