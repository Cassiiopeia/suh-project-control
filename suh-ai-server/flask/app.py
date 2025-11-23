"""
Flask OCR API
REST API for Ollama OCR service
"""
from flask import Flask, request, jsonify
from ocr_service import OCRService
import logging

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize OCR service
ocr_service = OCRService()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'ollama-ocr-api'
    }), 200


@app.route('/ocr', methods=['POST'])
def ocr():
    """
    OCR endpoint

    Request Body:
    {
        "image_url": "https://...",     # OR
        "image_base64": "base64string",
        "prompt": "Extract all text",   # Optional
        "model": "deepseek-ocr"        # Optional
    }

    Response:
    {
        "success": true,
        "result": "extracted text",
        "model": "deepseek-ocr",
        "prompt": "..."
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        # Extract parameters
        prompt = data.get('prompt', 'Extract all text from this image')
        model = data.get('model', 'deepseek-ocr')

        # Process image source
        if 'image_url' in data:
            logger.info(f"Processing image from URL: {data['image_url']}")
            base64_image = ocr_service.get_image_base64(data['image_url'])
        elif 'image_base64' in data:
            logger.info("Processing base64 image")
            base64_image = data['image_base64']
        else:
            return jsonify({
                'error': 'Either image_url or image_base64 required'
            }), 400

        # Perform OCR
        result = ocr_service.perform_ocr(base64_image, prompt, model)

        logger.info(f"OCR completed successfully (model={model})")

        return jsonify({
            'success': True,
            'result': result,
            'model': model,
            'prompt': prompt
        }), 200

    except FileNotFoundError as e:
        logger.error(f"File not found: {str(e)}")
        return jsonify({'error': str(e)}), 404

    except Exception as e:
        logger.error(f"OCR error: {str(e)}")
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500


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
