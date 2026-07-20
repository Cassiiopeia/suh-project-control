"""
Production server runner for Flask OCR API
Uses Waitress WSGI server (Windows compatible)
"""
from waitress import serve
from app import app
import logging
import os
import threading

# Create logs directory if not exists
logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Configure logging
log_file = os.path.join(logs_dir, 'flask_ocr.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("Starting Flask OCR API (Production Mode)")
    logger.info("=" * 50)
    logger.info(f"Server: http://0.0.0.0:5000")
    logger.info(f"Nginx Proxy: http://your-server:11436")
    logger.info(f"Log file: {log_file}")
    logger.info("=" * 50)

    # 감사로그 DB 마이그레이션 (yoyo — 실패해도 기동 계속)
    from config.db_config import apply_migrations
    apply_migrations()

    # 팰월드 접속/퇴장 이벤트 폴러 + 메트릭 히스토리 적재 (daemon thread)
    from service.palworld_service import PalworldService
    from service.palworld_event_poller import PalworldEventPoller
    from service.palworld_metrics_history import metrics_history
    PalworldEventPoller(PalworldService(), metrics_history=metrics_history).start()
    logger.info("Palworld event poller started (10s interval, metrics history on)")

    # 시스템 리소스 메트릭 폴러 (daemon thread) — 대시보드 CPU/MEM/GPU 카드용
    from service.system_metrics_service import SystemMetricsPoller
    SystemMetricsPoller().start()
    logger.info("System metrics poller started (10s interval)")

    # 팰월드 서버 바이너리 새 빌드 자동 감지 (daemon thread)
    from service import palworld_updater
    threading.Thread(target=palworld_updater.auto_check_loop, daemon=True,
                     name='palworld-update-checker').start()
    logger.info("Palworld auto-update checker started")

    # Start production server
    serve(
        app,
        host='0.0.0.0',
        port=5000,
        threads=16,  # TTS 합성 등 장시간 요청과 폴링이 겹쳐도 여유 있게
        url_scheme='http'
    )
