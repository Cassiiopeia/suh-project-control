"""
Common utility functions for image processing
"""
import base64
import tempfile
import os
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def download_image_from_url(url: str, timeout: int = 30) -> bytes:
    """
    Download image from URL
    
    Args:
        url: Image URL
        timeout: Request timeout in seconds
        
    Returns:
        Image content as bytes
        
    Raises:
        requests.RequestException: If download fails
    """
    logger.info(f"Downloading image from URL: {url}")
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def save_bytes_to_temp_file(content: bytes, suffix: str = '.jpg') -> str:
    """
    Save bytes content to temporary file
    
    Args:
        content: File content as bytes
        suffix: File suffix (e.g., '.jpg', '.png')
        
    Returns:
        Path to temporary file
        
    Raises:
        IOError: If file write fails
    """
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        temp_file.write(content)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        if temp_file:
            temp_file.close()
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
        raise


def file_to_base64(file_path: str) -> str:
    """
    Convert file to base64 encoded string
    
    Args:
        file_path: Path to file
        
    Returns:
        Base64 encoded string
        
    Raises:
        FileNotFoundError: If file not found
        IOError: If file read fails
    """
    logger.info(f"Encoding file to base64: {file_path}")
    with open(file_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def bytes_to_base64(content: bytes) -> str:
    """
    Convert bytes to base64 encoded string
    
    Args:
        content: File content as bytes
        
    Returns:
        Base64 encoded string
    """
    return base64.b64encode(content).decode('utf-8')


def base64_to_file(base64_string: str, output_path: str) -> None:
    """
    Convert base64 string to file
    
    Args:
        base64_string: Base64 encoded string
        output_path: Path to save file
        
    Raises:
        ValueError: If base64 string is invalid
        IOError: If file write fails
    """
    try:
        decoded = base64.b64decode(base64_string)
        with open(output_path, 'wb') as f:
            f.write(decoded)
        logger.info(f"Base64 decoded and saved to: {output_path}")
    except Exception as e:
        raise ValueError(f"Invalid base64 string: {str(e)}")


def clean_base64_string(base64_string: str) -> str:
    """
    Clean base64 string by removing data URL prefix and whitespace
    
    Args:
        base64_string: Base64 string (may include data URL prefix)
        
    Returns:
        Cleaned base64 string
        
    Raises:
        ValueError: If base64 string is invalid after cleaning
    """
    if not base64_string or not isinstance(base64_string, str):
        raise ValueError("Base64 string must be a non-empty string")
    
    # Strip whitespace
    cleaned = base64_string.strip()
    
    # Remove data URL prefix if present (e.g., "data:image/jpeg;base64,...")
    if cleaned.startswith('data:'):
        if ',' in cleaned:
            cleaned = cleaned.split(',', 1)[1].strip()
        else:
            raise ValueError("Invalid data URL format - missing comma separator")
    
    # Validate non-empty after processing
    if not cleaned:
        raise ValueError("Empty base64 string after cleaning")
    
    return cleaned


def validate_url(url: str) -> bool:
    """
    Validate URL format
    
    Args:
        url: URL string to validate
        
    Returns:
        True if valid URL format, False otherwise
    """
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    return url.startswith(('http://', 'https://'))

