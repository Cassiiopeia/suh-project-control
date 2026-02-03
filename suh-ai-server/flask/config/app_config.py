"""
Flask application configuration
"""

# Swagger UI configuration
SWAGGER_URL = '/api/flask/docs/swagger'
API_URL = '/api/flask/docs/swagger.json'

# Default OCR settings
DEFAULT_PROMPT = 'Extract all text from this image'
DEFAULT_MODEL = 'deepseek-ocr'

# Supported OCR models
SUPPORTED_MODELS = [
    # GLM-OCR models (recommended for complex documents)
    "glm-ocr",         # latest (2.2GB, 128K context)
    "glm-ocr:q8_0",    # quantized version (1.6GB)
    "glm-ocr:bf16",    # BF16 version (2.2GB)
    # Other vision models
    "deepseek-ocr",
    "qwen3-vl",
    "qwen2.5vl",
    "granite3.2-vision",
    "minicpm-v",
    "llava-phi3"
]

