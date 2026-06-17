"""
Vision Request/Response Models
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class VisionUrlRequest:
    image_url: str
    prompt: Optional[str] = "이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘."
    model: Optional[str] = "gemma3:4b"


@dataclass
class VisionUrlResponse:
    success: bool
    result: str
    model: str
    prompt: str


@dataclass
class VisionBase64Request:
    image_base64: str
    prompt: Optional[str] = "이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘."
    model: Optional[str] = "gemma3:4b"


@dataclass
class VisionBase64Response:
    success: bool
    result: str
    model: str
    prompt: str


@dataclass
class VisionUploadRequest:
    file: object
    prompt: Optional[str] = "이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘."
    model: Optional[str] = "gemma3:4b"


@dataclass
class VisionUploadResponse:
    success: bool
    result: str
    model: str
    prompt: str


@dataclass
class VisionRequest:
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    prompt: Optional[str] = "이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘."
    model: Optional[str] = "gemma3:4b"


@dataclass
class VisionResponse:
    success: bool
    result: str
    model: str
    prompt: str
