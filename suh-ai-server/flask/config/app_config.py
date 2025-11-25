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
    "deepseek-ocr",
    "qwen3-vl",
    "qwen2.5vl",
    "granite3.2-vision",
    "minicpm-v",
    "llava-phi3"
]

