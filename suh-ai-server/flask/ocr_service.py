"""
Ollama OCR Service
Converts PowerShell OCR script logic to Python
"""
import ollama
import requests
import base64
import tempfile
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OCRService:
    """Handles OCR operations using Ollama"""

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url

    def get_image_base64(self, source: str) -> str:
        """
        Convert image to Base64 (from URL or local file)

        Args:
            source: URL or local file path

        Returns:
            Base64 encoded image string

        Raises:
            FileNotFoundError: If image source not found
            requests.RequestException: If URL download fails
        """
        temp_file = None

        try:
            # Check if source is URL
            if source.startswith(('http://', 'https://')):
                logger.info(f"Downloading image from URL: {source}")
                response = requests.get(source, timeout=30)
                response.raise_for_status()

                # Save to temporary file
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                temp_file.write(response.content)
                temp_file.close()
                image_path = temp_file.name

            # Local file
            elif os.path.exists(source):
                logger.info(f"Reading local image: {source}")
                image_path = source

            else:
                raise FileNotFoundError(f"Image source not found: {source}")

            # Base64 encoding
            logger.info("Encoding to base64...")
            with open(image_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')

        finally:
            # Cleanup temporary file
            if temp_file and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)

    def perform_ocr(self, base64_image: str, prompt: str, model: str) -> str:
        """
        Perform OCR using Ollama

        Args:
            base64_image: Base64 encoded image
            prompt: OCR prompt
            model: Ollama model name

        Returns:
            Extracted text from image

        Raises:
            Exception: If Ollama API call fails
        """
        logger.info(f"Sending to Ollama ({model})...")

        try:
            response = ollama.chat(
                model=model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [base64_image]
                }]
            )

            return response['message']['content']

        except Exception as e:
            raise Exception(f"Ollama API error: {str(e)}")
