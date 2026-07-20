"""
Swagger router
"""
from flask import Blueprint, jsonify
from config.app_config import SWAGGER_URL, API_URL
from router.palworld_swagger import PALWORLD_SWAGGER_PATHS
from router.tts_swagger import TTS_SWAGGER_PATHS
from router.audit_swagger import AUDIT_SWAGGER_PATHS

swagger_bp = Blueprint('swagger', __name__)


@swagger_bp.route('/api/flask/docs/swagger.json', methods=['GET'])
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
            "/ocr/url": {
                "post": {
                    "tags": ["OCR"],
                    "summary": "Perform OCR on an image from URL",
                    "description": "Extract text from an image using image URL",
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
                                                "glm-ocr",
                                                "glm-ocr:q8_0",
                                                "glm-ocr:bf16",
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
                            "description": "OCR completed successfully"
                        },
                        "400": {
                            "description": "Bad request - missing or invalid parameters"
                        },
                        "404": {
                            "description": "Image not found"
                        },
                        "500": {
                            "description": "Internal server error"
                        }
                    }
                }
            },
            "/ocr/base64": {
                "post": {
                    "tags": ["OCR"],
                    "summary": "Perform OCR on a base64 encoded image",
                    "description": "Extract text from a base64 encoded image",
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
                                    "required": ["image_base64"],
                                    "properties": {
                                        "image_base64": {
                                            "type": "string",
                                            "description": "Base64 encoded image (with or without data URL prefix)",
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
                                                "glm-ocr",
                                                "glm-ocr:q8_0",
                                                "glm-ocr:bf16",
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
                            "description": "OCR completed successfully"
                        },
                        "400": {
                            "description": "Bad request - missing or invalid parameters"
                        },
                        "500": {
                            "description": "Internal server error"
                        }
                    }
                }
            },
            "/ocr/upload": {
                "post": {
                    "tags": ["OCR"],
                    "summary": "Perform OCR on an uploaded image file",
                    "description": "Extract text from an uploaded image file (multipart/form-data)",
                    "security": [
                        {
                            "ApiKeyAuth": []
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {
                                            "type": "string",
                                            "format": "binary",
                                            "description": "Image file to upload"
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
                                                "glm-ocr",
                                                "glm-ocr:q8_0",
                                                "glm-ocr:bf16",
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
                            "description": "OCR completed successfully"
                        },
                        "400": {
                            "description": "Bad request - missing or invalid file"
                        },
                        "500": {
                            "description": "Internal server error"
                        }
                    }
                }
            },
            "/logs": {
                "get": {
                    "tags": ["Logs"],
                    "summary": "서버 로그 조회 (JSON)",
                    "description": "최근 서버 로그를 JSON 형식으로 반환합니다. 레벨 필터 및 키워드 검색을 지원합니다.",
                    "security": [
                        {
                            "ApiKeyAuth": []
                        }
                    ],
                    "parameters": [
                        {
                            "name": "lines",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "default": 50,
                                "maximum": 500
                            },
                            "description": "최근 N줄 (기본: 50, 최대: 500)"
                        },
                        {
                            "name": "level",
                            "in": "query",
                            "schema": {
                                "type": "string",
                                "enum": ["INFO", "ERROR", "WARNING"]
                            },
                            "description": "로그 레벨 필터"
                        },
                        {
                            "name": "search",
                            "in": "query",
                            "schema": {
                                "type": "string"
                            },
                            "description": "키워드 검색"
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "로그 조회 성공"
                        },
                        "404": {
                            "description": "로그 파일 없음"
                        },
                        "500": {
                            "description": "서버 오류"
                        }
                    }
                }
            },
            "/logs/stream": {
                "get": {
                    "tags": ["Logs"],
                    "summary": "서버 로그 조회 (Plain Text)",
                    "description": "최근 서버 로그를 텍스트로 반환합니다. 브라우저에서 바로 보기 편합니다.",
                    "security": [
                        {
                            "ApiKeyAuth": []
                        }
                    ],
                    "parameters": [
                        {
                            "name": "lines",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "default": 100,
                                "maximum": 500
                            },
                            "description": "최근 N줄 (기본: 100, 최대: 500)"
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "로그 조회 성공 (text/plain)"
                        },
                        "404": {
                            "description": "로그 파일 없음"
                        },
                        "500": {
                            "description": "서버 오류"
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
                                    "properties": {
                                        "image_url": {
                                            "type": "string",
                                            "format": "uri",
                                            "description": "URL of the image to process (either image_url or image_base64 required)",
                                            "example": "https://example.com/image.jpg"
                                        },
                                        "image_base64": {
                                            "type": "string",
                                            "description": "Base64 encoded image (alternative to image_url, either image_url or image_base64 required)",
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
                                                "glm-ocr",
                                                "glm-ocr:q8_0",
                                                "glm-ocr:bf16",
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
                            "description": "OCR completed successfully"
                        },
                        "400": {
                            "description": "Bad request - missing required parameters"
                        },
                        "404": {
                            "description": "Image not found"
                        },
                        "500": {
                            "description": "Internal server error"
                        }
                    }
                }
            }
        }
    }
    swagger_spec["paths"].update(PALWORLD_SWAGGER_PATHS)
    swagger_spec["paths"].update(TTS_SWAGGER_PATHS)
    swagger_spec["paths"].update(AUDIT_SWAGGER_PATHS)
    return jsonify(swagger_spec), 200

