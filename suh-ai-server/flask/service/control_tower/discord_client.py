"""디스코드 REST 클라이언트: 알림 발송(실패해도 예외 없음), 채널·역할·온보딩 관리(실패 시 DiscordError)
공통 요청 1곳: 429 > retry_after 대기 후 1회, 5xx·네트워크 오류 > 1초 후 1회, 그 외 4xx > 재시도 없음
"""
from __future__ import annotations

import logging
import math
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://discord.com/api/v10"
# 요청 1건 타임아웃 (초)
REQUEST_TIMEOUT_SECONDS = 10
# 429 대기 상한 (초), retry_after가 더 커도 이 값까지만 대기
MAX_RETRY_AFTER_SECONDS = 30.0
# 5xx·네트워크 오류 재시도 전 대기 (초)
SERVER_ERROR_RETRY_DELAY_SECONDS = 1.0
# 감사 로그 사유 (변경 호출에만)
AUDIT_LOG_REASON = "SUH control tower sync"
# 오류 사유 최대 길이 (디스코드 message 필드 기준)
ERROR_REASON_MAX_LENGTH = 200
STATUS_TOO_MANY_REQUESTS = 429
STATUS_SERVER_ERROR_MIN = 500
# 네트워크 오류로 응답이 없을 때 DiscordError.status_code
STATUS_NO_RESPONSE = 0


class DiscordError(Exception):
    """디스코드 호출 최종 실패: 상태 코드 + 짧은 사유 (토큰·응답 본문 미포함)"""

    def __init__(self, status_code: int, reason: str):
        super().__init__(f"discord request failed : status {status_code} : {reason}")
        self.status_code = status_code
        self.reason = reason


class DiscordClient:
    def __init__(self, bot_token: str, guild_id: str, session: requests.Session | None = None, sleep=time.sleep):
        self._bot_token = bot_token
        self._guild_id = guild_id
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep

    def send_embed(self, channel_id: str, embed: dict) -> bool:
        """채널에 임베드 1건 발송 (멘션 차단, 최종 실패는 False로 흡수)"""
        payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}
        try:
            self._request("POST", f"/channels/{channel_id}/messages", json=payload)
        except DiscordError as error:
            logger.warning("[control-tower discord] send failed : status %s", error.status_code)
            return False
        return True

    def list_channels(self) -> list[dict]:
        return self._request("GET", f"/guilds/{self._guild_id}/channels")

    def create_channel(self, name: str, channel_type: int, parent_id: str | None, overwrites: list[dict]) -> dict:
        payload = {"name": name, "type": channel_type, "permission_overwrites": overwrites}
        if parent_id:
            payload["parent_id"] = parent_id
        return self._request("POST", f"/guilds/{self._guild_id}/channels", json=payload, is_mutation=True)

    def edit_channel(self, channel_id: str, **fields) -> dict:
        return self._request("PATCH", f"/channels/{channel_id}", json=fields, is_mutation=True)

    def list_roles(self) -> list[dict]:
        return self._request("GET", f"/guilds/{self._guild_id}/roles")

    def create_role(self, name: str) -> dict:
        payload = {"name": name, "mentionable": False, "hoist": False}
        return self._request("POST", f"/guilds/{self._guild_id}/roles", json=payload, is_mutation=True)

    def put_onboarding(self, payload: dict) -> bool:
        """온보딩 설정: 성공 True, 실패 False (커뮤니티 서버가 아니면 불가, 예외 없음)"""
        try:
            self._request("PUT", f"/guilds/{self._guild_id}/onboarding", json=payload, is_mutation=True)
        except DiscordError as error:
            logger.warning("[control-tower discord] onboarding failed : status %s", error.status_code)
            return False
        return True

    def _request(self, method: str, path: str, json: dict | None = None, is_mutation: bool = False):
        """요청 1건 (최대 2회 시도): 성공 응답 JSON 반환, 최종 실패는 DiscordError"""
        headers = {"Authorization": f"Bot {self._bot_token}"}
        if is_mutation:
            headers["X-Audit-Log-Reason"] = AUDIT_LOG_REASON

        last_error: DiscordError | None = None
        for attempt_number in (1, 2):
            retry_delay_seconds = None
            try:
                response = self._session.request(method, f"{BASE_URL}{path}", json=json, headers=headers,
                                                 timeout=REQUEST_TIMEOUT_SECONDS)
            except requests.RequestException as error:
                last_error = DiscordError(STATUS_NO_RESPONSE, type(error).__name__)
                retry_delay_seconds = SERVER_ERROR_RETRY_DELAY_SECONDS
            else:
                if 200 <= response.status_code < 300:
                    return self._parse_json(response)
                last_error = DiscordError(response.status_code, self._error_reason(response))
                if response.status_code == STATUS_TOO_MANY_REQUESTS:
                    retry_delay_seconds = self._retry_after_seconds(response)
                elif response.status_code >= STATUS_SERVER_ERROR_MIN:
                    retry_delay_seconds = SERVER_ERROR_RETRY_DELAY_SECONDS

            # 재시도 대상 아님(그 외 4xx) 또는 두 번째 시도 실패
            if retry_delay_seconds is None or attempt_number == 2:
                break
            self._sleep(retry_delay_seconds)
        raise last_error

    @staticmethod
    def _parse_json(response):
        try:
            return response.json()
        except ValueError:
            return {}

    @classmethod
    def _error_reason(cls, response) -> str:
        """디스코드 message 필드만 200자로 자름 (본문 전체·토큰 미포함)"""
        body = cls._parse_json(response)
        message = body.get("message") if isinstance(body, dict) else None
        return str(message or "")[:ERROR_REASON_MAX_LENGTH]

    @classmethod
    def _retry_after_seconds(cls, response) -> float:
        """429 대기 시간: JSON retry_after > 헤더 Retry-After > 상한 적용 (숫자 아님·NaN·무한대 > 기본 대기)"""
        body = cls._parse_json(response)
        raw_value = body.get("retry_after") if isinstance(body, dict) else None
        if raw_value is None:
            raw_value = response.headers.get("Retry-After")
        try:
            retry_after_seconds = float(raw_value)
        except (TypeError, ValueError):
            retry_after_seconds = SERVER_ERROR_RETRY_DELAY_SECONDS
        if not math.isfinite(retry_after_seconds):
            retry_after_seconds = SERVER_ERROR_RETRY_DELAY_SECONDS
        return min(max(retry_after_seconds, 0.0), MAX_RETRY_AFTER_SECONDS)
