"""프로젝트 썸네일 처리: 업로드·URL 이미지 > 검증 > 정사각 128px WebP, 주소 가져오기는 사설망 차단
상태 페이지(Worker)가 자체 서빙하는 이미지라 크기·형식을 서버에서 한 번 더 고정한다"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

# 저장 이미지 한 변 (픽셀, 정사각)
ICON_SIDE_PIXELS = 128
# 원본 최대 크기 (2MB) / 원본 최대 화소 수 (디코드 폭탄 방지)
SOURCE_MAX_BYTES = 2 * 1024 * 1024
SOURCE_MAX_PIXELS = 25_000_000
# 저장 WebP 최대 크기 (Worker base64 한도 40,000자 아래로, 약 30KB)
ICON_MAX_BYTES = 30_000
# WebP 품질 시도 순서 (첫 값에서 크기 안에 들어오면 끝)
WEBP_QUALITY_STEPS = (90, 80, 70, 60, 50)
# 읽을 수 있는 원본 형식 (SVG는 지원 안 함)
ACCEPTED_SOURCE_FORMATS = ("PNG", "JPEG", "WEBP", "GIF", "ICO")
# 주소 가져오기: 제한 시간(초) / 리다이렉트 최대 횟수
FETCH_TIMEOUT_SECONDS = 8
FETCH_MAX_REDIRECTS = 3
# 해시 앞 12자가 상태 페이지 캐시 주소의 버전
CONTENT_HASH_LENGTH = 12
HTTP_REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)


class ProjectIconError(Exception):
    """code: invalid_image | image_too_large | icon_fetch_failed"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def decode_base64_image(image_base64: str) -> bytes:
    """base64 문자열(data: 접두사 허용) > 원본 바이트, 크기 초과·잘못된 base64는 오류"""
    payload = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
    try:
        raw_bytes = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ProjectIconError("invalid_image") from None
    if len(raw_bytes) > SOURCE_MAX_BYTES:
        raise ProjectIconError("image_too_large")
    return raw_bytes


def normalize_icon(raw_bytes: bytes) -> tuple[bytes, str]:
    """원본 이미지 > (128px 정사각 WebP 바이트, 내용 해시 12자): 형식·화소 수 검사 > 가운데 잘라 맞춤 > 크기 안에 들 때까지 품질 낮춤"""
    if len(raw_bytes) > SOURCE_MAX_BYTES:
        raise ProjectIconError("image_too_large")
    try:
        with Image.open(io.BytesIO(raw_bytes)) as source_image:
            if source_image.format not in ACCEPTED_SOURCE_FORMATS:
                raise ProjectIconError("invalid_image")
            if source_image.width * source_image.height > SOURCE_MAX_PIXELS:
                raise ProjectIconError("image_too_large")
            oriented_image = ImageOps.exif_transpose(source_image).convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ProjectIconError("invalid_image") from None
    square_image = ImageOps.fit(oriented_image, (ICON_SIDE_PIXELS, ICON_SIDE_PIXELS), Image.Resampling.LANCZOS)
    webp_bytes = _encode_within_size_limit(square_image)
    return webp_bytes, hashlib.sha256(webp_bytes).hexdigest()[:CONTENT_HASH_LENGTH]


def _encode_within_size_limit(image: Image.Image) -> bytes:
    """품질을 낮춰 가며 ICON_MAX_BYTES 이하로 인코딩 (끝까지 안 들어오면 오류)"""
    for quality in WEBP_QUALITY_STEPS:
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=quality, method=6)
        if buffer.tell() <= ICON_MAX_BYTES:
            return buffer.getvalue()
    raise ProjectIconError("image_too_large")


def is_public_address(address_text: str) -> bool:
    """공인 주소만 true (사설·루프백·링크로컬·예약·멀티캐스트·미지정 제외)"""
    address = ipaddress.ip_address(address_text)
    return address.is_global and not address.is_multicast


def _assert_public_https_url(url: str) -> None:
    """https만 허용하고 호스트가 풀리는 모든 주소가 공인 주소일 때만 통과 (사설망 접근 차단)"""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ProjectIconError("icon_fetch_failed")
    try:
        address_infos = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ProjectIconError("icon_fetch_failed") from None
    if not address_infos or not all(is_public_address(info[4][0]) for info in address_infos):
        raise ProjectIconError("icon_fetch_failed")


def fetch_icon_bytes(url: str, session: requests.Session | None = None) -> bytes:
    """주소 > 원본 이미지 바이트: 리다이렉트는 직접 따라가며 매번 공인 주소 검사, 크기 상한까지만 읽음"""
    http_session = session if session is not None else requests.Session()
    current_url = url
    for _ in range(FETCH_MAX_REDIRECTS + 1):
        _assert_public_https_url(current_url)
        try:
            response = http_session.get(current_url, timeout=FETCH_TIMEOUT_SECONDS, allow_redirects=False, stream=True)
        except requests.RequestException:
            raise ProjectIconError("icon_fetch_failed") from None
        try:
            if response.status_code in HTTP_REDIRECT_STATUS_CODES:
                location = response.headers.get("Location")
                if not location:
                    raise ProjectIconError("icon_fetch_failed")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code != 200:
                raise ProjectIconError("icon_fetch_failed")
            return _read_limited_body(response)
        finally:
            response.close()
    raise ProjectIconError("icon_fetch_failed")


def _read_limited_body(response) -> bytes:
    """본문을 SOURCE_MAX_BYTES까지만 읽음 (초과하면 오류)"""
    chunks, total_bytes = [], 0
    for chunk in response.iter_content(chunk_size=16384):
        total_bytes += len(chunk)
        if total_bytes > SOURCE_MAX_BYTES:
            raise ProjectIconError("image_too_large")
        chunks.append(chunk)
    return b"".join(chunks)
