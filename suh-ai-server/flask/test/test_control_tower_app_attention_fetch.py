"""앱 확인할 일 수집 1회: 요청 형태(토큰·ETag·리다이렉트), 응답 분류 7종, 64KB 제한, 느린 본문, 토큰 비노출"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import requests

from service.control_tower.app_attention_fetch import fetch_attention
from service.control_tower.app_attention_store import AttentionSource

BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
TOKEN = "pull-secret"
SNAPSHOT = {"schema": "attention", "version": "1.0", "source": {"app": "elum-server"},
            "generated_at": "2026-11-08T12:00:00Z", "items": []}


class FakeResponse:
    def __init__(self, status_code=200, body: bytes = b"", headers=None, chunk_bytes=8192):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.chunk_bytes = chunk_bytes
        self.is_closed = False
        self.read_bytes = 0

    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), self.chunk_bytes):
            chunk = self.body[start:start + self.chunk_bytes]
            self.read_bytes += len(chunk)
            yield chunk

    def close(self):
        self.is_closed = True


class FakeHttpGet:
    """응답 1개 또는 예외를 돌려주고 호출 인자 기록"""

    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _source(url="https://elum.example/attention") -> AttentionSource:
    return AttentionSource("elum", "api", url, True, "pull", 60, 5, 300, BASE_TIME, BASE_TIME)


@pytest.fixture(autouse=True)
def pull_token(monkeypatch):
    monkeypatch.setenv("CONTROL_PULL_TOKEN_ELUM__API", TOKEN)


def test_정상_응답은_토큰_헤더와_etag로_요청하고_리다이렉트를_따르지_않는다():
    response = FakeResponse(body=json.dumps(SNAPSHOT).encode(), headers={"ETag": '"v2"'})
    http_get = FakeHttpGet(response)
    outcome = fetch_attention(_source(), '"v1"', http_get)
    assert outcome.result == "ok" and outcome.document == SNAPSHOT and outcome.etag == '"v2"'
    url, kwargs = http_get.calls[0]
    assert url == "https://elum.example/attention"
    assert kwargs["headers"]["X-Control-Token"] == TOKEN and kwargs["headers"]["If-None-Match"] == '"v1"'
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True and kwargs["timeout"] == 5
    assert response.is_closed


def test_주소의_환경변수를_치환하고_없는_변수면_요청하지_않는다(monkeypatch):
    monkeypatch.setenv("ELUM_HOST", "api.elum.internal")
    http_get = FakeHttpGet(FakeResponse(body=json.dumps(SNAPSHOT).encode()))
    fetch_attention(_source("http://${ELUM_HOST}/attention"), None, http_get)
    assert http_get.calls[0][0] == "http://api.elum.internal/attention"
    assert "If-None-Match" not in http_get.calls[0][1]["headers"]

    monkeypatch.delenv("ELUM_HOST")
    missing_get = FakeHttpGet(FakeResponse())
    outcome = fetch_attention(_source("http://${ELUM_HOST}/attention"), None, missing_get)
    assert (outcome.result, outcome.error_label) == ("error", "url_env_missing") and missing_get.calls == []


def test_수집_토큰이_없으면_요청하지_않고_unauthorized다(monkeypatch):
    monkeypatch.delenv("CONTROL_PULL_TOKEN_ELUM__API")
    http_get = FakeHttpGet(FakeResponse())
    outcome = fetch_attention(_source(), None, http_get)
    assert (outcome.result, outcome.error_label) == ("unauthorized", "token_missing") and http_get.calls == []


@pytest.mark.parametrize("status_code, expected", [
    (304, ("not_modified", None)), (401, ("unauthorized", "http_401")), (403, ("unauthorized", "http_403")),
    (404, ("disabled", "http_404")), (503, ("error", "http_503")), (302, ("error", "http_302")),
    (204, ("error", "http_204")),
])
def test_상태_코드별로_결과를_분류한다(status_code, expected):
    outcome = fetch_attention(_source(), '"v1"', FakeHttpGet(FakeResponse(status_code)))
    assert (outcome.result, outcome.error_label) == expected and outcome.document is None


def test_304는_받은_etag가_없으면_보낸_etag를_유지한다():
    assert fetch_attention(_source(), '"v1"', FakeHttpGet(FakeResponse(304))).etag == '"v1"'


def test_본문이_64KB를_넘으면_더_읽지_않고_too_large다():
    response = FakeResponse(body=b"x" * 200_000)
    outcome = fetch_attention(_source(), None, FakeHttpGet(response))
    assert (outcome.result, outcome.error_label) == ("invalid", "too_large")
    assert response.read_bytes <= 65536 + 8192


def test_길이_헤더가_64KB를_넘으면_본문을_읽지_않는다():
    response = FakeResponse(body=b"{}", headers={"Content-Length": "70000"})
    outcome = fetch_attention(_source(), None, FakeHttpGet(response))
    assert outcome.error_label == "too_large" and response.read_bytes == 0


def test_정확히_64KB인_JSON은_받는다():
    padding = 65536 - len(json.dumps({**SNAPSHOT, "pad": ""}).encode())
    body = json.dumps({**SNAPSHOT, "pad": "a" * padding}).encode()
    assert len(body) == 65536
    assert fetch_attention(_source(), None, FakeHttpGet(FakeResponse(body=body))).result == "ok"


@pytest.mark.parametrize("body", [b"<html>oops</html>", b"\xff\xfe\x00", b""])
def test_JSON이_아닌_본문은_not_json이다(body):
    outcome = fetch_attention(_source(), None, FakeHttpGet(FakeResponse(body=body)))
    assert (outcome.result, outcome.error_label) == ("invalid", "not_json")


@pytest.mark.parametrize("error, expected", [
    (requests.exceptions.ReadTimeout(), ("timeout", "timeout")),
    (requests.exceptions.ConnectionError(), ("error", "connection_error")),
    (requests.exceptions.SSLError(), ("error", "tls_error")),
    (ValueError("boom"), ("error", "error")),
])
def test_요청_예외는_check_runner_라벨로_분류한다(error, expected):
    outcome = fetch_attention(_source(), None, FakeHttpGet(error=error))
    assert (outcome.result, outcome.error_label) == expected


def test_본문을_조금씩_보내_소스_timeout을_넘기면_timeout이다():
    clock = iter([0.0, 1.0, 3.0, 6.0, 9.0])
    response = FakeResponse(body=b"x" * 40, chunk_bytes=10)
    outcome = fetch_attention(_source(), None, FakeHttpGet(response), monotonic=lambda: next(clock))
    assert (outcome.result, outcome.error_label) == ("timeout", "timeout") and response.is_closed


def test_결과_어디에도_토큰_값이_남지_않는다():
    for response in (FakeResponse(401), FakeResponse(body=b"bad"), FakeResponse(body=json.dumps(SNAPSHOT).encode())):
        assert TOKEN not in repr(fetch_attention(_source(), None, FakeHttpGet(response)))
