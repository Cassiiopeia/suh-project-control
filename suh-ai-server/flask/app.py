"""
Flask OCR API
REST API for Ollama OCR service
"""
from flask import Flask, jsonify
from flask_swagger_ui import get_swaggerui_blueprint
from router.ocr_router import ocr_bp
from router.swagger_router import swagger_bp
from config.app_config import SWAGGER_URL, API_URL
from config.logging_config import setup_logging

# Initialize Flask app
app = Flask(__name__)

# Setup logging
logger = setup_logging()

# Swagger UI configuration
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={
        'app_name': "Flask OCR API"
    }
)
app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)

# Register routers
app.register_blueprint(ocr_bp)
app.register_blueprint(swagger_bp)


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    # Development mode only
    logger.warning("Running in development mode")
    logger.info("Flask OCR API starting on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
