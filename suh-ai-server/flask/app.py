"""
Flask OCR API
REST API for Ollama OCR service
"""
from flask import Flask, request, jsonify
from flask_swagger_ui import get_swaggerui_blueprint
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

# Swagger UI configuration
SWAGGER_URL = '/docs/swagger'
API_URL = '/docs/swagger.json'

swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={
        'app_name': "Flask OCR API"
    }
)
app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)


@app.route('/docs/swagger.json', methods=['GET'])
def swagger_json():
    """Swagger API specification"""
    swagger_spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Flask OCR API",
            "version": "1.0.0",
            "description": "OCR API using Ollama vision models"
        },
        "servers": [
            {
                "url": "/api/flask",
                "description": "Production server"
            }
        ],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                    "description": "API Key for authentication (optional - Nginx handles auth)"
                }
            }
        },
        "security": [
            {
                "ApiKeyAuth": []
            }
        ],
        "paths": {
            "/health": {
                "get": {
                    "tags": ["Health"],
                    "summary": "Health check endpoint",
                    "description": "Returns the health status of the API",
                    "responses": {
                        "200": {
                            "description": "Service is healthy",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {
                                                "type": "string",
                                                "example": "healthy"
                                            },
                                            "service": {
                                                "type": "string",
                                                "example": "ollama-ocr-api"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/ocr": {
                "post": {
                    "tags": ["OCR"],
                    "summary": "Perform OCR on an image",
                    "description": "Extract text from an image using Ollama vision models",
                    "security": [
                        {
                            "ApiKeyAuth": []
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["image_url"],
                                    "properties": {
                                        "image_url": {
                                            "type": "string",
                                            "format": "uri",
                                            "description": "URL of the image to process",
                                            "example": "https://example.com/image.jpg"
                                        },
                                        "image_base64": {
                                            "type": "string",
                                            "description": "Base64 encoded image (alternative to image_url)",
                                            "example": "iVBORw0KGgoAAAANSUhEUgAA..."
                                        },
                                        "prompt": {
                                            "type": "string",
                                            "description": "OCR prompt (optional)",
                                            "default": "Extract all text from this image",
                                            "example": "Extract all text from this image"
                                        },
                                        "model": {
                                            "type": "string",
                                            "description": "Ollama model name (optional)",
                                            "default": "deepseek-ocr",
                                            "enum": [
                                                "deepseek-ocr",
                                                "qwen3-vl",
                                                "qwen2.5vl",
                                                "granite3.2-vision",
                                                "minicpm-v",
                                                "llava-phi3"
                                            ],
                                            "example": "deepseek-ocr"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "OCR completed successfully",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {
                                                "type": "boolean",
                                                "example": True
                                            },
                                            "result": {
                                                "type": "string",
                                                "description": "Extracted text from image",
                                                "example": "Extracted text content..."
                                            },
                                            "model": {
                                                "type": "string",
                                                "example": "deepseek-ocr"
                                            },
                                            "prompt": {
                                                "type": "string",
                                                "example": "Extract all text from this image"
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "400": {
                            "description": "Bad request - missing required parameters",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {
                                                "type": "string",
                                                "example": "Either image_url or image_base64 required"
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "404": {
                            "description": "Image not found",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {
                                                "type": "string",
                                                "example": "Image source not found: https://example.com/image.jpg"
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "500": {
                            "description": "Internal server error",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {
                                                "type": "string",
                                                "example": "OCR failed: Ollama API error"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    return jsonify(swagger_spec), 200


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
