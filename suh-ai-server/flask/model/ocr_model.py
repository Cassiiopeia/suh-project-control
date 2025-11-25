"""
OCR Request/Response Models
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class OcrUrlRequest:
    """Request model for OCR URL endpoint"""
    image_url: str
    prompt: Optional[str] = "Extract all text from this image"
    model: Optional[str] = "deepseek-ocr"


@dataclass
class OcrUrlResponse:
    """Response model for OCR URL endpoint"""
    success: bool
    result: str
    model: str
    prompt: str


@dataclass
class OcrBase64Request:
    """Request model for OCR Base64 endpoint"""
    image_base64: str
    prompt: Optional[str] = "Extract all text from this image"
    model: Optional[str] = "deepseek-ocr"


@dataclass
class OcrBase64Response:
    """Response model for OCR Base64 endpoint"""
    success: bool
    result: str
    model: str
    prompt: str


@dataclass
class OcrUploadRequest:
    """Request model for OCR Upload endpoint"""
    file: object  # Flask file object
    prompt: Optional[str] = "Extract all text from this image"
    model: Optional[str] = "deepseek-ocr"


@dataclass
class OcrUploadResponse:
    """Response model for OCR Upload endpoint"""
    success: bool
    result: str
    model: str
    prompt: str


@dataclass
class OcrRequest:
    """Request model for OCR endpoint (supports both URL and Base64)"""
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    prompt: Optional[str] = "Extract all text from this image"
    model: Optional[str] = "deepseek-ocr"


@dataclass
class OcrResponse:
    """Response model for OCR endpoint"""
    success: bool
    result: str
    model: str
    prompt: str

