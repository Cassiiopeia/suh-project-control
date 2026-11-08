"""관제소 심박 클라이언트: Worker에 서명한 심박 전송 > 설정 요청 시 스냅샷 1회 재전송 > 외부 점검 결과 수신
연결 실패·타임아웃 > None, Worker 응답했지만 거절(2xx 외·잘못된 JSON) > HeartbeatRejectedError (비밀키·본문 미기록)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests

from service.control_tower.check_runner import CheckResult
from service.control_tower.registry import MaintenanceWindow, Registry

logger = logging.getLogger(__name__)

HEARTBEAT_PATH = "/api/heartbeat"
# 요청 1건 타임아웃 (초)
REQUEST_TIMEOUT_SECONDS = 10
# 서명 헤더: unix 초 / hex(HMAC-SHA256(secret, "{timestamp}.{raw_body}"))
TIMESTAMP_HEADER = "X-CT-Timestamp"
SIGNATURE_HEADER = "X-CT-Signature"
CONTENT_TYPE = "application/json; charset=utf-8"
HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX = 299
# 거절 사유: 2xx지만 JSON 객체가 아닌 응답
REJECTION_INVALID_RESPONSE = "invalid_response"
# 집 인터넷 장애로 보는 전송 실패 (연결 실패·TLS 포함·타임아웃)
NETWORK_FAILURE_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)


class HeartbeatRejectedError(Exception):
    """Worker가 응답했지만 심박을 받지 않음: 상태 코드 문자열 또는 invalid_response (집 인터넷 장애 아님)"""

    def __init__(self, rejection_status: str):
        super().__init__(f"heartbeat rejected : {rejection_status}")
        self.rejection_status = rejection_status


@dataclass(frozen=True)
class HeartbeatResponse:
    external_results: dict[str, CheckResult]  # service_id > Worker 최신 외부 점검 결과
    checked_at: datetime | None  # Worker 점검 시각, 없으면 외부 결과도 없음


def sign(secret: str, timestamp: int, raw_body: bytes) -> str:
    """서명: hex(HMAC-SHA256(secret, "{timestamp}." + 본문 바이트))"""
    message = f"{timestamp}.".encode("utf-8") + raw_body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


class HeartbeatClient:
    def __init__(self, worker_url: str, secret: str, session: requests.Session | None = None):
        self._heartbeat_url = worker_url.rstrip("/") + HEARTBEAT_PATH
        self._secret = secret
        self._session = session if session is not None else requests.Session()

    def send(self, registry: Registry, public_incidents: list[dict], now: datetime,
             maintenance: Iterable[MaintenanceWindow] | None = None,
             project_icons: dict[str, bytes] | None = None) -> HeartbeatResponse | None:
        """심박 1회: 전송 > need_config면 스냅샷(+썸네일) 넣어 1회 재전송 > 외부 결과 변환
        maintenance: 등록 파일 + 관리자 화면 병합 창 (버전·스냅샷 모두 같은 창 기준), 거절 시 HeartbeatRejectedError
        project_icons: project_id > WebP 바이트, 스냅샷을 실을 때만 base64로 동봉"""
        windows = None if maintenance is None else tuple(maintenance)
        body = {"sent_at": now.isoformat(), "config_version": registry.version(windows),
                "public_incidents": public_incidents}
        response_body = self._post(body, now)
        if response_body is not None and response_body.get("need_config") is True:
            response_body = self._post({**body, "config": registry.to_worker_snapshot(windows),
                                        "project_icons": _encode_project_icons(project_icons)}, now)
        if response_body is None:
            return None
        # 재전송 후에도 설정 요청이면 결과 없이 심박 성공으로 처리
        if response_body.get("need_config") is True:
            logger.warning("[control-tower heartbeat] worker still requests config after resend")
            return HeartbeatResponse({}, None)
        return _parse_response(response_body)

    def _post(self, body: dict, now: datetime) -> dict | None:
        """서명 POST: 직렬화 바이트 그대로 서명·전송 > 2xx JSON 객체 반환 / 연결 실패 None / 거절 예외"""
        raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timestamp = int(now.timestamp())
        headers = {
            "Content-Type": CONTENT_TYPE,
            TIMESTAMP_HEADER: str(timestamp),
            SIGNATURE_HEADER: sign(self._secret, timestamp, raw_body),
        }
        try:
            response = self._session.post(self._heartbeat_url, data=raw_body, headers=headers,
                                          timeout=REQUEST_TIMEOUT_SECONDS)
        except NETWORK_FAILURE_ERRORS as error:  # 네트워크 오류 종류만 기록 (예외 문구 미기록)
            logger.warning("[control-tower heartbeat] failed : %s", type(error).__name__)
            return None
        if not HTTP_SUCCESS_MIN <= response.status_code <= HTTP_SUCCESS_MAX:
            logger.warning("[control-tower heartbeat] rejected : status %s", response.status_code)
            raise HeartbeatRejectedError(str(response.status_code))
        try:
            response_body = response.json()
        except ValueError:
            response_body = None
        if not isinstance(response_body, dict):
            logger.warning("[control-tower heartbeat] rejected : status %s : response is not a JSON object",
                           response.status_code)
            raise HeartbeatRejectedError(REJECTION_INVALID_RESPONSE)
        return response_body


def _encode_project_icons(project_icons: dict[str, bytes] | None) -> dict[str, str]:
    """project_id > WebP 바이트를 base64 문자열로 (Worker 심박 본문 형식)"""
    return {project_id: base64.b64encode(image_bytes).decode("ascii")
            for project_id, image_bytes in (project_icons or {}).items()}


def _parse_response(response_body: dict) -> HeartbeatResponse:
    """응답 > 외부 결과 (checked_at 없거나 잘못되면 결과 없음, 형태가 잘못된 항목은 건너뜀)"""
    checked_at = _parse_utc_datetime(response_body.get("checked_at"))
    raw_results = response_body.get("external_results")
    if checked_at is None or not isinstance(raw_results, dict):
        return HeartbeatResponse({}, None)
    external_results = {}
    for service_id, raw_result in raw_results.items():
        result = _to_check_result(raw_result, checked_at)
        if result is not None:
            external_results[service_id] = result
    return HeartbeatResponse(external_results, checked_at)


def _to_check_result(raw_result, checked_at: datetime) -> CheckResult | None:
    """Worker 결과 1건 {is_ok, is_slow, status_code, latency_milliseconds, error} > CheckResult"""
    if not isinstance(raw_result, dict) or not isinstance(raw_result.get("is_ok"), bool):
        return None
    status_code = raw_result.get("status_code")
    latency_milliseconds = raw_result.get("latency_milliseconds")
    error = raw_result.get("error")
    return CheckResult(
        is_ok=raw_result["is_ok"],
        is_slow=raw_result.get("is_slow") is True,
        status_code=status_code if isinstance(status_code, int) and not isinstance(status_code, bool) else None,
        latency_milliseconds=int(latency_milliseconds) if _is_finite_number(latency_milliseconds) else 0,
        error=error if isinstance(error, str) else None,
        checked_at=checked_at,
    )


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_utc_datetime(value) -> datetime | None:
    """ISO 문자열 > aware datetime ('Z' 허용, 시간대 없으면 UTC), 잘못되면 None"""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
