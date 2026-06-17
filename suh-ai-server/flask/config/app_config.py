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

# Default Vision settings
DEFAULT_VISION_PROMPT = '이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘.'
DEFAULT_VISION_MODEL = 'gemma3:4b'

# Supported Vision models (tested, responds within 120s)
SUPPORTED_VISION_MODELS = [
    "gemma3:4b",        # recommended — best Korean quality (55s)
    "gemma4:e2b",       # good Korean (65s)
    "minicpm-v4.6",     # fast but English-heavy (16s)
    "llava:7b",         # Korean capable but hallucination-prone (72s)
    "deepseek-ocr:3b",  # English only (47s)
]

