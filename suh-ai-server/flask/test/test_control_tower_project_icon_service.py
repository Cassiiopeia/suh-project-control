"""관제소 프로젝트 썸네일 처리: 정규화(정사각 128px WebP·크기·형식·화소 수), base64 해독, 주소 가져오기(사설망 차단·리다이렉트·크기)"""
from __future__ import annotations

import base64
import io
import socket

import pytest
import requests
from PIL import Image

from service.control_tower import project_icon_service
from service.control_tower.project_icon_service import (
    ICON_MAX_BYTES, ICON_SIDE_PIXELS, SOURCE_MAX_BYTES, ProjectIconError, decode_base64_image, fetch_icon_bytes,
    is_public_address, normalize_icon,
)

PUBLIC_ADDRESS_INFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
PRIVATE_ADDRESS_INFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.10", 443))]


def make_image_bytes(image_format: str = "PNG", size: tuple[int, int] = (300, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 80, 20)).save(buffer, format=image_format)
    return buffer.getvalue()


# ---- normalize_icon ----

@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "GIF", "WEBP"])
def test_지원_형식은_128px_정사각_webp로_바뀐다(image_format):
    image_webp, content_hash = normalize_icon(make_image_bytes(image_format))

    result_image = Image.open(io.BytesIO(image_webp))
    assert result_image.format == "WEBP"
    assert result_image.size == (ICON_SIDE_PIXELS, ICON_SIDE_PIXELS)
    assert len(image_webp) <= ICON_MAX_BYTES
    assert len(content_hash) == 12


def test_가로로_긴_이미지는_가운데를_잘라_정사각으로_맞춘다():
    image_webp, _ = normalize_icon(make_image_bytes("PNG", (600, 100)))

    assert Image.open(io.BytesIO(image_webp)).size == (ICON_SIDE_PIXELS, ICON_SIDE_PIXELS)


def test_같은_이미지는_같은_해시_다른_이미지는_다른_해시():
    _, first_hash = normalize_icon(make_image_bytes("PNG", (300, 200)))
    _, same_hash = normalize_icon(make_image_bytes("PNG", (300, 200)))
    other_buffer = io.BytesIO()
    Image.new("RGB", (300, 200), (10, 10, 10)).save(other_buffer, format="PNG")
    _, other_hash = normalize_icon(other_buffer.getvalue())

    assert first_hash == same_hash and first_hash != other_hash


def test_이미지가_아닌_바이트는_invalid_image():
    with pytest.raises(ProjectIconError) as error:
        normalize_icon(b"<html>not an image</html>")

    assert error.value.code == "invalid_image"


def test_지원하지_않는_형식은_invalid_image():
    with pytest.raises(ProjectIconError) as error:
        normalize_icon(make_image_bytes("BMP"))

    assert error.value.code == "invalid_image"


def test_원본_크기_초과는_image_too_large():
    with pytest.raises(ProjectIconError) as error:
        normalize_icon(b"0" * (SOURCE_MAX_BYTES + 1))

    assert error.value.code == "image_too_large"


def test_화소_수가_너무_많으면_image_too_large(monkeypatch):
    monkeypatch.setattr(project_icon_service, "SOURCE_MAX_PIXELS", 1000)

    with pytest.raises(ProjectIconError) as error:
        normalize_icon(make_image_bytes("PNG", (100, 100)))

    assert error.value.code == "image_too_large"


# ---- decode_base64_image ----

def test_base64는_순수_문자열과_data_url_둘_다_해독한다():
    raw_bytes = make_image_bytes("PNG")
    encoded = base64.b64encode(raw_bytes).decode("ascii")

    assert decode_base64_image(encoded) == raw_bytes
    assert decode_base64_image("data:image/png;base64," + encoded) == raw_bytes


def test_잘못된_base64는_invalid_image():
    with pytest.raises(ProjectIconError) as error:
        decode_base64_image("***not-base64***")

    assert error.value.code == "invalid_image"


def test_해독_결과가_크기_초과면_image_too_large():
    encoded = base64.b64encode(b"0" * (SOURCE_MAX_BYTES + 1)).decode("ascii")

    with pytest.raises(ProjectIconError) as error:
        decode_base64_image(encoded)

    assert error.value.code == "image_too_large"


# ---- is_public_address ----

@pytest.mark.parametrize("address, expected", [
    ("93.184.216.34", True), ("8.8.8.8", True), ("2606:4700:4700::1111", True),
    ("127.0.0.1", False), ("10.0.0.5", False), ("192.168.0.10", False), ("172.16.3.4", False),
    ("169.254.169.254", False), ("0.0.0.0", False), ("::1", False), ("fe80::1", False), ("224.0.0.1", False),
])
def test_공인_주소만_통과한다(address, expected):
    assert is_public_address(address) is expected


# ---- fetch_icon_bytes ----

class FakeFetchResponse:
    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.is_closed = False

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self):
        self.is_closed = True


class FakeFetchSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url, timeout=None, allow_redirects=None, stream=None):
        self.urls.append(url)
        assert allow_redirects is False  # 리다이렉트는 직접 따라가며 매번 검사
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(project_icon_service.socket, "getaddrinfo", lambda *arguments, **keywords: PUBLIC_ADDRESS_INFO)


def test_https_공인_주소는_본문을_돌려준다(public_dns):
    session = FakeFetchSession(FakeFetchResponse(body=b"image-bytes"))

    assert fetch_icon_bytes("https://lab.example.com/logo.png", session) == b"image-bytes"
    assert session.urls == ["https://lab.example.com/logo.png"]


def test_http_주소는_거부한다(public_dns):
    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("http://lab.example.com/logo.png", FakeFetchSession())

    assert error.value.code == "icon_fetch_failed"


def test_사설_주소로_풀리는_호스트는_요청하지_않고_거부한다(monkeypatch):
    monkeypatch.setattr(project_icon_service.socket, "getaddrinfo", lambda *arguments, **keywords: PRIVATE_ADDRESS_INFO)
    session = FakeFetchSession()

    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("https://nas.example.com/logo.png", session)

    assert error.value.code == "icon_fetch_failed" and session.urls == []


def test_주소가_풀리지_않으면_icon_fetch_failed(monkeypatch):
    def fail(*arguments, **keywords):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(project_icon_service.socket, "getaddrinfo", fail)

    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("https://missing.example.com/logo.png", FakeFetchSession())

    assert error.value.code == "icon_fetch_failed"


def test_리다이렉트는_따라가고_마지막_응답을_쓴다(public_dns):
    session = FakeFetchSession(
        FakeFetchResponse(302, headers={"Location": "/images/logo.png"}), FakeFetchResponse(body=b"final"))

    assert fetch_icon_bytes("https://lab.example.com/favicon.ico", session) == b"final"
    assert session.urls == ["https://lab.example.com/favicon.ico", "https://lab.example.com/images/logo.png"]


def test_리다이렉트_대상이_사설망이면_거부한다(monkeypatch):
    answers = iter([PUBLIC_ADDRESS_INFO, PRIVATE_ADDRESS_INFO])
    monkeypatch.setattr(project_icon_service.socket, "getaddrinfo", lambda *arguments, **keywords: next(answers))
    session = FakeFetchSession(FakeFetchResponse(302, headers={"Location": "https://internal.example.com/x"}))

    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("https://lab.example.com/logo.png", session)

    assert error.value.code == "icon_fetch_failed" and len(session.urls) == 1


def test_리다이렉트가_너무_많으면_거부한다(public_dns):
    redirects = [FakeFetchResponse(302, headers={"Location": "https://lab.example.com/next"}) for _ in range(10)]

    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("https://lab.example.com/start", FakeFetchSession(*redirects))

    assert error.value.code == "icon_fetch_failed"


def test_200이_아니면_icon_fetch_failed(public_dns):
    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("https://lab.example.com/logo.png", FakeFetchSession(FakeFetchResponse(404)))

    assert error.value.code == "icon_fetch_failed"


def test_본문이_상한을_넘으면_image_too_large(public_dns):
    session = FakeFetchSession(FakeFetchResponse(body=b"0" * (SOURCE_MAX_BYTES + 1)))

    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("https://lab.example.com/logo.png", session)

    assert error.value.code == "image_too_large"


def test_네트워크_오류는_icon_fetch_failed(public_dns):
    with pytest.raises(ProjectIconError) as error:
        fetch_icon_bytes("https://lab.example.com/logo.png", FakeFetchSession(requests.ConnectionError("down")))

    assert error.value.code == "icon_fetch_failed"


def test_응답은_항상_닫는다(public_dns):
    response = FakeFetchResponse(body=b"ok")

    fetch_icon_bytes("https://lab.example.com/logo.png", FakeFetchSession(response))

    assert response.is_closed is True
