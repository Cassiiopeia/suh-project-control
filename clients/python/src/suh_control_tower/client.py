"""관제소 이벤트 입구 클라이언트: 본문 조립 > POST /control/events > 결과 변환"""
import json
import socket
import threading
import urllib.error
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

FieldsInput = Union[Mapping[str, Any], Iterable[Tuple[str, Any]]]


class ControlTowerClient:
    """관제소 알림 전송: 스레드 안전 (요청마다 연결을 새로 만들고 상태를 바꾸지 않음)"""

    def __init__(self, project: str, token: str, base_url: str = DEFAULT_BASE_URL,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
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
        """요청 본문 조립 (값이 없는 선택 필드는 생략)"""
        payload = {"project": self._project, "kind": kind, "severity": severity, "title": title}
        if body is not None:
            payload["body"] = body
        if url is not None:
            payload["url"] = url
        if dedupe_key is not None:
            payload["dedupe_key"] = dedupe_key
        if fields is not None:
            pairs = fields.items() if isinstance(fields, Mapping) else fields
            payload["fields"] = [{"name": str(name), "value": str(value)} for name, value in pairs]
        return payload

    def notify(self, kind: str, title: str, fields: Optional[FieldsInput] = None,
               body: Optional[str] = None, url: Optional[str] = None,
               severity: str = "info", dedupe_key: Optional[str] = None) -> NotifyResult:
        """알림 1건 전송: 본문 조립 > POST > 결과 변환 (예외를 던지지 않음)"""
        try:
            payload = self.build_payload(kind, title, fields, body, url, severity, dedupe_key)
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except Exception:
            return NotifyResult(is_accepted=False, error_code="invalid")
        request = urllib.request.Request(self._events_url, data=raw_body, method="POST", headers={
            "Content-Type": "application/json; charset=utf-8",
            TOKEN_HEADER_NAME: self._token,
        })
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
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

    def notify_in_background(self, *args, **kwargs) -> threading.Thread:
        """notify를 데몬 스레드에서 실행하고 즉시 반환 (결과는 버림)"""
        thread = threading.Thread(target=self.notify, args=args, kwargs=kwargs, daemon=True)
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
        is_deduplicated = bool(parsed.get("deduplicated")) if isinstance(parsed, dict) else False
        return NotifyResult(is_accepted=True, status_code=status_code, is_deduplicated=is_deduplicated)
    server_error = parsed.get("error") if isinstance(parsed, dict) else None
    error_code = server_error if isinstance(server_error, str) else "http_%d" % status_code
    return NotifyResult(is_accepted=False, status_code=status_code, error_code=error_code)
