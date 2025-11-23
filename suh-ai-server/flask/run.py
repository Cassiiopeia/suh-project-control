"""
Production server runner for Flask OCR API
Uses Waitress WSGI server (Windows compatible)
"""
from waitress import serve
from app import app
import logging
import os

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

    # Start production server
    serve(
        app,
        host='0.0.0.0',
        port=5000,
        threads=4,
        url_scheme='http'
    )
