"""
Ollama Vision Service
Image description using local vision models via Ollama
"""
import os
import logging
from ollama import Client, ChatResponse
from util.common_util import (
    download_image_from_url,
    save_bytes_to_temp_file,
    file_to_base64,
    bytes_to_base64,
    clean_base64_string,
    validate_url
)

logger = logging.getLogger(__name__)


class VisionService:
    """Handles image description using Ollama vision models"""

    def __init__(self, ollama_url: str = "http://127.0.0.1:11434"):
        self.ollama_url = ollama_url.rstrip('/')
        self.client = Client(host=self.ollama_url)

    def get_image_base64(self, source: str) -> str:
        temp_file_path = None
        try:
            if validate_url(source):
                image_content = download_image_from_url(source)
                temp_file_path = save_bytes_to_temp_file(image_content, suffix='.jpg')
                return file_to_base64(temp_file_path)
            elif os.path.exists(source):
                logger.info(f"Reading local image: {source}")
                return file_to_base64(source)
            else:
                raise FileNotFoundError(f"Image source not found: {source}")
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    def get_image_base64_from_file(self, file) -> str:
        if not file or not file.filename:
            raise ValueError("No file provided")
        file_content = file.read()
        if not file_content:
            raise ValueError("Empty file")
        logger.info(f"Encoding uploaded file to base64: {file.filename}")
        return bytes_to_base64(file_content)

    def process_base64_image(self, image_base64: str) -> str:
        return clean_base64_string(image_base64)

    def process_image_url(self, image_url: str) -> str:
        if not image_url or not isinstance(image_url, str):
            raise ValueError("image_url is required")
        image_url = image_url.strip()
        if not validate_url(image_url):
            raise ValueError("Invalid image_url format - must be a valid HTTP/HTTPS URL")
        return self.get_image_base64(image_url)

    def describe_image(self, base64_image: str, prompt: str, model: str) -> str:
        """
        Describe image content using Ollama vision model

        Args:
            base64_image: Base64 encoded image
            prompt: Description prompt
            model: Ollama vision model name (e.g., 'gemma3:4b', 'minicpm-v4.6')

        Returns:
            Image description text
        """
        logger.info(f"Sending to Ollama ({model}) at {self.ollama_url}...")
        try:
            response: ChatResponse = self.client.chat(
                model=model,
                messages=[
                    {
                        'role': 'user',
                        'content': prompt,
                        'images': [base64_image]
                    }
                ]
            )
            result = response.message.content
            logger.info(f"Vision description completed, {len(result)} characters")
            return result
        except Exception as e:
            logger.error(f"Ollama Vision failed: {str(e)}")
            raise Exception(f"Ollama API error: {str(e)}")
