"""
Ollama OCR Service
Converts PowerShell OCR script logic to Python
"""
import os
import logging
import requests
from util.common_util import (
    download_image_from_url,
    save_bytes_to_temp_file,
    file_to_base64,
    bytes_to_base64,
    clean_base64_string,
    validate_url
)

logger = logging.getLogger(__name__)


class OCRService:
    """Handles OCR operations using Ollama"""

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url.rstrip('/')

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
        temp_file_path = None

        try:
            # Check if source is URL
            if validate_url(source):
                # Download from URL
                image_content = download_image_from_url(source)
                temp_file_path = save_bytes_to_temp_file(image_content, suffix='.jpg')
                return file_to_base64(temp_file_path)

            # Local file
            elif os.path.exists(source):
                logger.info(f"Reading local image: {source}")
                return file_to_base64(source)

            else:
                raise FileNotFoundError(f"Image source not found: {source}")

        finally:
            # Cleanup temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    def get_image_base64_from_file(self, file) -> str:
        """
        Convert uploaded file to Base64

        Args:
            file: Flask file object (from request.files)

        Returns:
            Base64 encoded image string

        Raises:
            ValueError: If file is invalid or empty
        """
        if not file or not file.filename:
            raise ValueError("No file provided")

        # Read file content
        file_content = file.read()
        if not file_content:
            raise ValueError("Empty file")

        # Encode to base64 using common util
        logger.info(f"Encoding uploaded file to base64: {file.filename}")
        return bytes_to_base64(file_content)
    
    def process_base64_image(self, image_base64: str) -> str:
        """
        Process and validate base64 image string
        
        Args:
            image_base64: Base64 encoded image string (may include data URL prefix)
            
        Returns:
            Cleaned base64 string
            
        Raises:
            ValueError: If base64 string is invalid
        """
        return clean_base64_string(image_base64)
    
    def process_image_url(self, image_url: str) -> str:
        """
        Process and validate image URL, then convert to base64
        
        Args:
            image_url: Image URL
            
        Returns:
            Base64 encoded image string
            
        Raises:
            ValueError: If URL is invalid
            FileNotFoundError: If image source not found
            requests.RequestException: If URL download fails
        """
        if not image_url or not isinstance(image_url, str):
            raise ValueError("image_url is required")
        
        image_url = image_url.strip()
        
        if not validate_url(image_url):
            raise ValueError("Invalid image_url format - must be a valid HTTP/HTTPS URL")
        
        return self.get_image_base64(image_url)

    def perform_ocr(self, base64_image: str, prompt: str, model: str) -> str:
        """
        Perform OCR using Ollama API (direct HTTP call, matching PowerShell script behavior)

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
            # Prepare API request body (matching PowerShell script format)
            api_url = f"{self.ollama_url}/api/chat"
            
            request_body = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [base64_image]
                    }
                ],
                "stream": False
            }
            
            logger.debug(f"Calling Ollama API: {api_url}")
            
            # Make HTTP request to Ollama API
            response = requests.post(
                api_url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=120  # OCR can take time
            )
            
            # Check response status
            response.raise_for_status()
            
            # Parse response
            result = response.json()
            
            if 'message' not in result or 'content' not in result['message']:
                raise ValueError(f"Invalid Ollama API response format: {result}")
            
            extracted_text = result['message']['content']
            logger.info(f"OCR completed successfully, extracted {len(extracted_text)} characters")
            
            return extracted_text

        except requests.exceptions.RequestException as e:
            error_msg = f"Ollama API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f" - Response: {error_detail}"
                except:
                    error_msg += f" - Status: {e.response.status_code}"
            logger.error(error_msg)
            raise Exception(f"Ollama API error: {error_msg}")
        
        except Exception as e:
            logger.error(f"Ollama OCR failed: {str(e)}")
            raise Exception(f"Ollama API error: {str(e)}")

