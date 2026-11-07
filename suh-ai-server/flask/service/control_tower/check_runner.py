"""관제소 점검 실행기: HTTP·TCP 1회 점검, 정상 판정, 지연 시간 측정, 실패 라벨 분류"""
from __future__ import annotations

import logging
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from service.control_tower.registry import CheckSpec

logger = logging.getLogger(__name__)

# 기본 규칙에서 장애로 보는 상태 코드: 게이트웨이 계열 + Cloudflare 엣지 오류 520~530 (프록시 뒤 원본 접속 불가)
FAILURE_STATUS_CODES = (502, 503, 504)
CLOUDFLARE_EDGE_ERROR_FIRST = 520
CLOUDFLARE_EDGE_ERROR_LAST = 530
MILLISECONDS_PER_SECOND = 1000

# 실패 라벨 4종 (외부 예외 문구는 저장하지 않음)
ERROR_LABEL_TIMEOUT = "timeout"
ERROR_LABEL_TLS = "tls_error"
ERROR_LABEL_CONNECTION = "connection_error"
ERROR_LABEL_UNKNOWN = "error"


@dataclass(frozen=True)
class CheckResult:
    is_ok: bool
    is_slow: bool  # 정상이면서 지연 시간 > slow 기준
    status_code: int | None  # TCP 점검과 연결 실패는 None
    latency_milliseconds: int
    error: str | None  # 실패 라벨, 성공이면 None
    checked_at: datetime


def utc_now() -> datetime:
    """현재 시각 (UTC, timezone 포함)"""
    return datetime.now(timezone.utc)


def is_status_ok(status_code: int, expect: tuple[int, ...]) -> bool:
    """상태 코드 정상 판정: expect 있으면 그 코드만, 없으면 502·503·504·520~530 외 전부 (Worker isStatusOk와 같은 표)"""
    if expect:
        return status_code in expect
    if CLOUDFLARE_EDGE_ERROR_FIRST <= status_code <= CLOUDFLARE_EDGE_ERROR_LAST:
        return False
    return status_code not in FAILURE_STATUS_CODES


def run_check(spec: CheckSpec, slow_milliseconds: int, http_get=requests.get,
              open_socket=socket.create_connection, now=utc_now, *, monotonic=time.monotonic) -> CheckResult:
    """점검 1회: 호출 > 지연 시간 측정 > 정상·slow 판정 (예외는 라벨로 변환)"""
    started_seconds = monotonic()
    try:
        status_code = _call_target(spec, http_get, open_socket)
    except Exception as exception:  # 점검은 어떤 실패도 결과로 돌려줌
        latency_milliseconds = _elapsed_milliseconds(started_seconds, monotonic)
        error_label = classify_error(exception)
        logger.info("[control-tower check] failed : kind=%s label=%s", spec.kind, error_label)
        return CheckResult(False, False, None, latency_milliseconds, error_label, now())

    latency_milliseconds = _elapsed_milliseconds(started_seconds, monotonic)
    is_ok = True if status_code is None else is_status_ok(status_code, spec.expect)
    is_slow = is_ok and latency_milliseconds > slow_milliseconds
    return CheckResult(is_ok, is_slow, status_code, latency_milliseconds, None, now())


def classify_error(exception: BaseException) -> str:
    """예외 > 라벨 (timeout / tls_error / connection_error / error), 순서 주의: TLS·timeout이 연결 오류의 하위 형태"""
    if isinstance(exception, (requests.exceptions.Timeout, TimeoutError, socket.timeout)):
        return ERROR_LABEL_TIMEOUT
    if isinstance(exception, (requests.exceptions.SSLError, ssl.SSLError)):
        return ERROR_LABEL_TLS
    if isinstance(exception, (requests.exceptions.ConnectionError, OSError)):
        return ERROR_LABEL_CONNECTION
    return ERROR_LABEL_UNKNOWN


def _call_target(spec: CheckSpec, http_get, open_socket) -> int | None:
    """대상 호출: http는 상태 코드, tcp는 None"""
    if spec.kind == "tcp":
        _connect_tcp(spec, open_socket)
        return None
    # 리다이렉트 미추적, stream=True로 본문 미다운로드 (헤더만 수신 후 close)
    response = http_get(spec.target, timeout=spec.timeout_seconds, allow_redirects=False, stream=True)
    try:
        return response.status_code
    finally:
        response.close()


def _connect_tcp(spec: CheckSpec, open_socket) -> None:
    """TCP 연결 후 즉시 종료 (target 형식: host:port)"""
    host, separator, port_text = spec.target.rpartition(":")
    if not separator or not host:
        raise ValueError("tcp target must be host:port")
    connection = open_socket((host, int(port_text)), spec.timeout_seconds)
    connection.close()


def _elapsed_milliseconds(started_seconds: float, monotonic) -> int:
    """시작 시각 > 경과 시간 (밀리초, 소수점 버림)"""
    return int((monotonic() - started_seconds) * MILLISECONDS_PER_SECOND)
