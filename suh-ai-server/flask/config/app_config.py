"""
Flask application configuration
"""

# Swagger UI configuration
SWAGGER_URL = '/api/flask/docs/swagger'
API_URL = '/api/flask/docs/swagger.json'

# Default OCR settings
DEFAULT_PROMPT = 'Extract all text from this image'
DEFAULT_MODEL = 'deepseek-ocr'

# Default Vision settings
DEFAULT_VISION_PROMPT = '이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘.'
DEFAULT_VISION_MODEL = 'gemma3:4b'
