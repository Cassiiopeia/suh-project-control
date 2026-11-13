"""관제소 이벤트 입구 클라이언트: 본문 조립 > POST /control/events > 결과 변환"""
import json
import math
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Mapping, Optional, Tuple, Union

from .result import NotifyResult

DEFAULT_BASE_URL = "https://ai.suhsaechan.kr/api/flask"
DEFAULT_TIMEOUT_SECONDS = 3
EVENTS_PATH = "/control/events"
TOKEN_HEADER_NAME = "X-Control-Token"
HTTP_ACCEPTED = 202

ERROR_CODE_TIMEOUT = "timeout"
ERROR_CODE_CONNECTION = "connection_error"
ERROR_CODE_NOT_INITIALIZED = "not_initialized"
ERROR_CODE_INVALID_INPUT = "invalid_input"  # 보내기 전 로컬 검증 실패 (서버의 invalid와 구분)

# 평문 http를 허용하는 호스트 (로컬 테스트 전용)
PLAINTEXT_ALLOWED_HOSTS = ("127.0.0.1", "localhost")

FieldsInput = Union[Mapping[str, Any], Iterable[Tuple[str, Any]]]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """리다이렉트 차단: 토큰 헤더가 다른 주소로 전달되지 않게 3xx를 그대로 결과로 돌림"""

    def redirect_request(self, *args, **kwargs):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _validate_configuration(project: str, token: str, base_url: str) -> None:
    """설정 검증 (project, token, base_url): 잘못되면 ValueError (토큰 값은 메시지에 넣지 않음)"""
    if not isinstance(project, str) or not project:
        raise ValueError("project must be a non-empty string")
    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    # 헤더 값으로 안전한 문자만: ASCII 인쇄 가능, 공백·제어문자 없음
    if not token.isascii() or any(ch.isspace() or not ch.isprintable() for ch in token):
        raise ValueError("token must not contain whitespace, control or non-ASCII characters")
    parsed = _parse_base_url(base_url)
    is_https = parsed is not None and parsed.scheme == "https" and bool(parsed.hostname)
    is_local_http = (parsed is not None and parsed.scheme == "http"
                     and parsed.hostname in PLAINTEXT_ALLOWED_HOSTS)
    if not (is_https or is_local_http):
        raise ValueError("base_url must be https (http only for 127.0.0.1 or localhost)")


def _parse_base_url(base_url: str):
    """base_url 파싱: 문자열 아님, 공백·제어문자, 잘못된 포트는 None (Java URI 검증과 같게)"""
    if not isinstance(base_url, str) or any(ch.isspace() or not ch.isprintable() for ch in base_url):
        return None
    try:
        parsed = urllib.parse.urlparse(base_url)
        parsed.port  # 잘못된 포트는 접근 시 ValueError
    except ValueError:
        return None
    return parsed


def _validate_timeout_seconds(timeout_seconds: float) -> None:
    """시간 제한 검증: 0보다 큰 유한 숫자 (bool 제외)"""
    is_number = isinstance(timeout_seconds, (int, float)) and not isinstance(timeout_seconds, bool)
    if not is_number or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive number")


def _to_field_text(value: Any) -> str:
    """필드 값 > 문자열 (bool은 Java와 같게 true/false, 그 외 str)"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class ControlTowerClient:
    """관제소 알림 전송: 스레드 안전 (요청마다 연결을 새로 만들고 상태를 바꾸지 않음)"""

    def __init__(self, *, project: str, token: str, base_url: str = DEFAULT_BASE_URL,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        _validate_configuration(project, token, base_url)
        _validate_timeout_seconds(timeout_seconds)
        self._project = project
        self._token = token
        self._events_url = base_url.rstrip("/") + EVENTS_PATH
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        # 토큰은 출력하지 않음
        return "ControlTowerClient(project=%r, events_url=%r)" % (self._project, self._events_url)

    def build_payload(self, kind: str, title: str, fields: Optional[FieldsInput] = None,
                      body: Optional[str] = None, url: Optional[str] = None,
                      severity: str = "info", dedupe_key: Optional[str] = None) -> dict:
        """요청 본문 조립 (kind·title 필수 문자열, severity 문자열, 값이 없는 선택 필드는 생략)"""
        if not isinstance(kind, str) or not kind or not isinstance(title, str) or not title:
            raise ValueError("kind and title must be non-empty strings")
        if not isinstance(severity, str):
            raise ValueError("severity must be a string")
        payload = {"project": self._project, "kind": kind, "severity": severity, "title": title}
        # 선택 문자열은 값이 있으면 str이어야 함 (Java는 String 타입)
        for optional_name, optional_value in (("body", body), ("url", url), ("dedupe_key", dedupe_key)):
            if optional_value is None:
                continue
            if not isinstance(optional_value, str):
                raise ValueError("%s must be a string" % optional_name)
            payload[optional_name] = optional_value
        if fields is not None:
            pairs = fields.items() if isinstance(fields, Mapping) else fields
            payload["fields"] = []
            for name, value in pairs:
                if name is None or value is None:
                    raise ValueError("field name and value must not be None")
                payload["fields"].append({"name": str(name), "value": _to_field_text(value)})
        return payload

    def notify(self, kind: str, title: str, fields: Optional[FieldsInput] = None,
               body: Optional[str] = None, url: Optional[str] = None,
               severity: str = "info", dedupe_key: Optional[str] = None) -> NotifyResult:
        """알림 1건 전송: 본문 조립 > POST > 결과 변환 (예외를 던지지 않음)"""
        try:
            payload = self.build_payload(kind, title, fields, body, url, severity, dedupe_key)
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except Exception:
            return NotifyResult(is_accepted=False, error_code=ERROR_CODE_INVALID_INPUT)
        request = urllib.request.Request(self._events_url, data=raw_body, method="POST", headers={
            "Content-Type": "application/json; charset=utf-8",
            TOKEN_HEADER_NAME: self._token,
        })
        try:
            with _NO_REDIRECT_OPENER.open(request, timeout=self._timeout_seconds) as response:
                return _to_result(response.status, response.read())
        except urllib.error.HTTPError as http_error:
            return _to_result(http_error.code, _read_quietly(http_error))
        except (socket.timeout, TimeoutError):
            return NotifyResult(is_accepted=False, error_code=ERROR_CODE_TIMEOUT)
        except urllib.error.URLError as url_error:
            is_timeout = isinstance(url_error.reason, (socket.timeout, TimeoutError))
            return NotifyResult(is_accepted=False,
                                error_code=ERROR_CODE_TIMEOUT if is_timeout else ERROR_CODE_CONNECTION)
        except Exception:
            return NotifyResult(is_accepted=False, error_code=ERROR_CODE_CONNECTION)

    def notify_in_background(self, kind: str, title: str, fields: Optional[FieldsInput] = None,
                             body: Optional[str] = None, url: Optional[str] = None,
                             severity: str = "info", dedupe_key: Optional[str] = None) -> threading.Thread:
        """notify를 데몬 스레드에서 실행하고 즉시 반환 (호출마다 스레드 1개, 결과는 버림, 종료 시 진행 중 전송은 유실)"""
        thread = threading.Thread(
            target=self.notify, args=(kind, title, fields, body, url, severity, dedupe_key), daemon=True)
        thread.start()
        return thread


def _read_quietly(http_error: urllib.error.HTTPError) -> bytes:
    try:
        return http_error.read()
    except Exception:
        return b""


def _to_result(status_code: int, raw_body: bytes) -> NotifyResult:
    """상태 코드 + 응답 본문 > NotifyResult (JSON이 아니면 http_<상태>)"""
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except Exception:
        parsed = None
    if status_code == HTTP_ACCEPTED:
        is_deduplicated = isinstance(parsed, dict) and parsed.get("deduplicated") is True
        return NotifyResult(is_accepted=True, status_code=status_code, is_deduplicated=is_deduplicated)
    server_error = parsed.get("error") if isinstance(parsed, dict) else None
    error_code = server_error if isinstance(server_error, str) else "http_%d" % status_code
    return NotifyResult(is_accepted=False, status_code=status_code, error_code=error_code)
