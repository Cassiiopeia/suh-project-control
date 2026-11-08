"""앱 확인할 일 수집 (pull) 1회: 주소 ${ENV} 치환 > 토큰 헤더 > GET > 응답 분류 (본문 64KB, 소스 timeout 안)
네트워크 외 부수효과 없음. 결과 분류 7종은 FETCH_RESULTS"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

import requests

from service.control_tower.app_attention_models import MAX_BODY_BYTES
from service.control_tower.app_attention_tokens import read_pull_token
from service.control_tower.check_runner import ERROR_LABEL_TIMEOUT, classify_error
from service.control_tower.registry_loader import _substitute_env_placeholders

logger = logging.getLogger(__name__)

# 수집 결과 7종 (ok·not_modified = 성공, 나머지 = 실패로 기록하고 마지막 항목 유지)
FETCH_RESULT_OK = "ok"
FETCH_RESULT_NOT_MODIFIED = "not_modified"
FETCH_RESULT_UNAUTHORIZED = "unauthorized"
FETCH_RESULT_DISABLED = "disabled"
FETCH_RESULT_INVALID = "invalid"
FETCH_RESULT_TIMEOUT = "timeout"
FETCH_RESULT_ERROR = "error"
FETCH_RESULTS = (FETCH_RESULT_OK, FETCH_RESULT_NOT_MODIFIED, FETCH_RESULT_UNAUTHORIZED, FETCH_RESULT_DISABLED,
                 FETCH_RESULT_INVALID, FETCH_RESULT_TIMEOUT, FETCH_RESULT_ERROR)

# 실패 사유 라벨 (외부 예외 문구·토큰 값은 남기지 않음)
ERROR_LABEL_TOKEN_MISSING = "token_missing"
ERROR_LABEL_URL_ENV_MISSING = "url_env_missing"
ERROR_LABEL_TOO_LARGE = "too_large"
ERROR_LABEL_NOT_JSON = "not_json"
HTTP_ERROR_LABEL_FORMAT = "http_{status_code}"

TOKEN_HEADER_NAME = "X-Control-Token"
READ_CHUNK_BYTES = 8192
HTTP_OK = 200
HTTP_NOT_MODIFIED = 304
HTTP_UNAUTHORIZED_CODES = (401, 403)
HTTP_NOT_FOUND = 404


@dataclass(frozen=True)
class FetchOutcome:
    """수집 1회 결과 (pull 응답 또는 push 본문을 같은 형태로)"""
    result: str  # FETCH_RESULTS 중 하나
    document: object | None  # 파싱한 JSON 본문 (ok일 때만)
    etag: str | None  # 다음 요청 If-None-Match 값
    error_label: str | None  # 실패 사유 (성공이면 None)


def fetch_attention(source, etag: str | None, http_get=requests.get, *, monotonic=time.monotonic) -> FetchOutcome:
    """소스 1건 수집: 주소 치환 > 토큰 확인(없으면 요청 안 함) > GET > 상태 코드·본문 분류 (예외는 라벨로)"""
    url = _resolve_url(source.url)
    if url is None:
        return _failure(FETCH_RESULT_ERROR, ERROR_LABEL_URL_ENV_MISSING)
    token = read_pull_token(source.project_id, source.source_id)
    if token is None:
        return _failure(FETCH_RESULT_UNAUTHORIZED, ERROR_LABEL_TOKEN_MISSING)

    headers = {TOKEN_HEADER_NAME: token, "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    started_seconds = monotonic()
    try:
        # 리다이렉트 미추적 (토큰이 다른 호스트로 새지 않게), stream으로 64KB까지만 읽기
        response = http_get(url, headers=headers, timeout=source.timeout_seconds, allow_redirects=False,
                            stream=True)
        try:
            return _classify_response(response, etag, source.timeout_seconds, started_seconds, monotonic)
        finally:
            response.close()
    except Exception as error:  # 수집 실패는 결과로 돌려줌 (폴러 틱 보호)
        error_label = classify_error(error)
        result = FETCH_RESULT_TIMEOUT if error_label == ERROR_LABEL_TIMEOUT else FETCH_RESULT_ERROR
        logger.info("[control-tower app-attention] fetch failed : source %s.%s : %s",
                    source.project_id, source.source_id, error_label)
        return _failure(result, error_label)


def _resolve_url(url: str) -> str | None:
    """주소 안 ${NAME} 치환 (registry_loader와 같은 규칙), 없는 변수가 있으면 None"""
    problems: list[str] = []
    resolved = _substitute_env_placeholders(url, os.environ, problems, "attention source url", set())
    return None if problems else resolved


def _classify_response(response, etag: str | None, timeout_seconds: float, started_seconds: float,
                       monotonic) -> FetchOutcome:
    """상태 코드 분류: 304 변화 없음, 401·403 인증, 404 꺼짐, 200 본문 읽기, 그 외 http_<code>"""
    status_code = response.status_code
    if status_code == HTTP_NOT_MODIFIED:
        return FetchOutcome(FETCH_RESULT_NOT_MODIFIED, None, response.headers.get("ETag") or etag, None)
    if status_code in HTTP_UNAUTHORIZED_CODES:
        return _failure(FETCH_RESULT_UNAUTHORIZED, HTTP_ERROR_LABEL_FORMAT.format(status_code=status_code))
    if status_code == HTTP_NOT_FOUND:
        return _failure(FETCH_RESULT_DISABLED, HTTP_ERROR_LABEL_FORMAT.format(status_code=status_code))
    if status_code != HTTP_OK:
        return _failure(FETCH_RESULT_ERROR, HTTP_ERROR_LABEL_FORMAT.format(status_code=status_code))

    body = _read_limited_body(response, timeout_seconds, started_seconds, monotonic)
    if body is None:
        return _failure(FETCH_RESULT_INVALID, ERROR_LABEL_TOO_LARGE)
    try:
        document = json.loads(body)
    except ValueError:  # UnicodeDecodeError 포함
        return _failure(FETCH_RESULT_INVALID, ERROR_LABEL_NOT_JSON)
    return FetchOutcome(FETCH_RESULT_OK, document, response.headers.get("ETag"), None)


def _read_limited_body(response, timeout_seconds: float, started_seconds: float, monotonic) -> bytes | None:
    """본문 읽기 (64KB 넘으면 None), 요청 시작부터 timeout 넘기면 TimeoutError (조금씩 보내는 응답 차단)"""
    declared_length = response.headers.get("Content-Length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    received_bytes = 0
    for chunk in response.iter_content(chunk_size=READ_CHUNK_BYTES):
        received_bytes += len(chunk)
        if received_bytes > MAX_BODY_BYTES:
            return None
        if monotonic() - started_seconds > timeout_seconds:
            raise TimeoutError("attention body read exceeded timeout")
        chunks.append(chunk)
    return b"".join(chunks)


def _failure(result: str, error_label: str) -> FetchOutcome:
    return FetchOutcome(result, None, None, error_label)
