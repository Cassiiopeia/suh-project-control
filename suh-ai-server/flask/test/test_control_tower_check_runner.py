"""관제소 점검 실행기: 상태 코드 판정표, 예외 라벨 매핑, 지연 시간·slow 판정, TCP 점검"""
from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone

import pytest
import requests

from service.control_tower.check_runner import CheckResult, is_status_ok, run_check, utc_now
from service.control_tower.registry import CheckSpec

SLOW_MILLISECONDS = 5000  # 테스트용 slow 기준
FIXED_NOW = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.is_closed = False

    def close(self):
        self.is_closed = True


class FakeSocket:
    def __init__(self):
        self.is_closed = False

    def close(self):
        self.is_closed = True


def make_clock(*elapsed_seconds: float):
    """monotonic 대역: 호출 순서대로 값을 돌려줌 (시작, 끝)"""
    values = iter(elapsed_seconds)
    return lambda: next(values)


def http_spec(expect: tuple[int, ...] = ()) -> CheckSpec:
    return CheckSpec("http", "https://example.com/health", expect, 7)


def run_http(http_get, spec: CheckSpec | None = None, clock=None) -> CheckResult:
    return run_check(
        spec or http_spec(), SLOW_MILLISECONDS, http_get=http_get,
        now=lambda: FIXED_NOW, monotonic=clock or make_clock(0.0, 0.1))


@pytest.mark.parametrize('code, expect, ok', [
    (200, (), True), (401, (), True), (404, (), True), (500, (), True),
    (502, (), False), (503, (), False), (504, (), False),
    (404, (200,), False), (200, (200,), True)])
def test_is_status_ok(code, expect, ok):
    assert is_status_ok(code, expect) is ok


def test_utc_now_is_timezone_aware_utc():
    assert utc_now().utcoffset() == timezone.utc.utcoffset(None)


def test_http_success_records_status_and_closes_response():
    response = FakeResponse(200)
    result = run_http(lambda url, **kwargs: response, clock=make_clock(10.0, 10.25))
    assert result == CheckResult(True, False, 200, 250, None, FIXED_NOW)
    assert response.is_closed


def test_http_failure_status_is_not_ok_and_not_slow():
    result = run_http(lambda url, **kwargs: FakeResponse(503), clock=make_clock(0.0, 9.0))
    assert (result.is_ok, result.is_slow, result.status_code, result.error) == (False, False, 503, None)


def test_http_timeout_is_failure_with_error_label():
    def raise_timeout(url, **kwargs):
        raise requests.exceptions.ConnectTimeout("secret detail")
    result = run_http(raise_timeout)
    assert (result.is_ok, result.is_slow, result.status_code, result.error) == (False, False, None, 'timeout')


def test_socket_timeout_is_timeout_label():
    def raise_timeout(url, **kwargs):
        raise socket.timeout()
    assert run_http(raise_timeout).error == 'timeout'


def test_connection_error_is_failure():
    def raise_connection_error(url, **kwargs):
        raise requests.exceptions.ConnectionError("secret detail")
    result = run_http(raise_connection_error)
    assert (result.is_ok, result.error) == (False, 'connection_error')


def test_tls_error_is_not_mistaken_for_connection_error():
    def raise_tls_error(url, **kwargs):
        raise requests.exceptions.SSLError("certificate verify failed")
    assert run_http(raise_tls_error).error == 'tls_error'


def test_standard_ssl_error_is_tls_error():
    def raise_tls_error(url, **kwargs):
        raise ssl.SSLError("handshake")
    assert run_http(raise_tls_error).error == 'tls_error'


def test_unexpected_exception_is_generic_error_without_message():
    def raise_unexpected(url, **kwargs):
        raise ValueError("https://user:token@example.com leaked")
    result = run_http(raise_unexpected)
    assert result.error == 'error'


def test_slow_response_marks_is_slow_but_ok():
    result = run_http(lambda url, **kwargs: FakeResponse(200), clock=make_clock(0.0, 6.0))
    assert (result.is_ok, result.is_slow, result.latency_milliseconds) == (True, True, 6000)


def test_latency_equal_to_threshold_is_not_slow():
    result = run_http(lambda url, **kwargs: FakeResponse(200), clock=make_clock(0.0, 5.0))
    assert result.is_slow is False


def test_expect_list_makes_other_codes_failure():
    result = run_http(lambda url, **kwargs: FakeResponse(404), spec=http_spec((200,)))
    assert (result.is_ok, result.status_code) == (False, 404)


def test_http_check_does_not_follow_redirects():
    calls = []

    def record_call(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(302)

    result = run_http(record_call)
    assert calls == [("https://example.com/health", {"timeout": 7, "allow_redirects": False})]
    assert result.is_ok  # 302도 응답이 왔으므로 정상


def test_tcp_check_success_and_refused():
    opened = FakeSocket()
    calls = []

    def open_socket(address, timeout):
        calls.append((address, timeout))
        return opened

    spec = CheckSpec("tcp", "db.internal:5432", (), 3)
    result = run_check(spec, SLOW_MILLISECONDS, open_socket=open_socket,
                       now=lambda: FIXED_NOW, monotonic=make_clock(0.0, 0.02))
    assert result == CheckResult(True, False, None, 20, None, FIXED_NOW)
    assert calls == [(("db.internal", 5432), 3)]
    assert opened.is_closed

    def refuse(address, timeout):
        raise ConnectionRefusedError()
    refused = run_check(spec, SLOW_MILLISECONDS, open_socket=refuse,
                        now=lambda: FIXED_NOW, monotonic=make_clock(0.0, 0.01))
    assert (refused.is_ok, refused.is_slow, refused.status_code, refused.error) == (False, False, None, 'connection_error')


def test_tcp_slow_connect_is_slow_but_ok():
    spec = CheckSpec("tcp", "db.internal:5432")
    result = run_check(spec, SLOW_MILLISECONDS, open_socket=lambda address, timeout: FakeSocket(),
                       now=lambda: FIXED_NOW, monotonic=make_clock(0.0, 5.5))
    assert (result.is_ok, result.is_slow) == (True, True)


def test_tcp_timeout_label():
    def time_out(address, timeout):
        raise socket.timeout()
    spec = CheckSpec("tcp", "db.internal:5432")
    result = run_check(spec, SLOW_MILLISECONDS, open_socket=time_out, now=lambda: FIXED_NOW,
                       monotonic=make_clock(0.0, 10.0))
    assert result.error == 'timeout'


def test_tcp_invalid_target_is_generic_error():
    spec = CheckSpec("tcp", "no-port-here")
    result = run_check(spec, SLOW_MILLISECONDS, open_socket=lambda address, timeout: FakeSocket(),
                       now=lambda: FIXED_NOW, monotonic=make_clock(0.0, 0.0))
    assert (result.is_ok, result.error) == (False, 'error')
