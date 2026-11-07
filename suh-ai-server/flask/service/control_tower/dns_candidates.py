"""관제소 Cloudflare DNS 후보: zone 조회 > 레코드 조회 > A/AAAA/CNAME만 > 등록된 외부 주소 호스트 제외
토큰은 헤더에만 싣고 로그·응답에 남기지 않음"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests

from service.control_tower.registry import Registry

logger = logging.getLogger(__name__)

# .env: Cloudflare API 토큰 (Zone.DNS 읽기) / 대상 zone 이름
CLOUDFLARE_API_TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
CLOUDFLARE_ZONE_NAME_ENV = "CLOUDFLARE_ZONE_NAME"
DEFAULT_CLOUDFLARE_ZONE_NAME = "suhsaechan.kr"
CLOUDFLARE_API_BASE_URL = "https://api.cloudflare.com/client/v4"
REQUEST_TIMEOUT_SECONDS = 10
# 한 번에 읽는 DNS 레코드 수 (Cloudflare 상한)
DNS_RECORDS_PER_PAGE = 500
# 후보로 보는 레코드 종류
CANDIDATE_RECORD_TYPES = ("A", "AAAA", "CNAME")
# 와일드카드 레코드 접두사 (주소로 쓸 수 없어 제외)
WILDCARD_PREFIX = "*"


class DnsLookupError(Exception):
    """Cloudflare 조회 실패 (reason: 응답에 싣는 짧은 사유 코드)"""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def registered_hosts(registry: Registry) -> set[str]:
    """등록된 외부 점검 주소의 호스트 (retired 포함, 소문자)"""
    hosts = set()
    for service in registry.services + registry.infrastructure:
        if service.external is not None and service.external.kind == "http":
            hostname = urlsplit(service.external.target).hostname
            if hostname:
                hosts.add(hostname.lower())
    return hosts


def fetch_dns_candidates(token: str, zone_name: str, excluded_hosts: set[str], session=None) -> list[dict]:
    """zone id 조회 > 레코드 조회 > 후보 필터 > [{hostname, type, is_proxied}] (호스트 이름순, 같은 이름 1건)"""
    http = session if session is not None else requests
    headers = {"Authorization": f"Bearer {token}"}
    zones = _get_result(http, f"{CLOUDFLARE_API_BASE_URL}/zones", {"name": zone_name}, headers)
    if not zones:
        raise DnsLookupError("zone_not_found")
    records = _get_result(http, f"{CLOUDFLARE_API_BASE_URL}/zones/{zones[0]['id']}/dns_records",
                          {"per_page": DNS_RECORDS_PER_PAGE}, headers)
    candidates: dict[str, dict] = {}
    for record in records:
        hostname = str(record.get("name", "")).lower()
        if (record.get("type") not in CANDIDATE_RECORD_TYPES or not hostname
                or hostname.startswith(WILDCARD_PREFIX) or hostname in excluded_hosts or hostname in candidates):
            continue
        candidates[hostname] = {"hostname": hostname, "type": record["type"],
                                "is_proxied": record.get("proxied") is True}
    return [candidates[hostname] for hostname in sorted(candidates)]


def _get_result(http, url: str, params: dict, headers: dict) -> list:
    """GET > success true 응답의 result 목록 (네트워크·상태 코드·형식 오류는 DnsLookupError)"""
    try:
        response = http.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        logger.warning("[control-tower dns] request failed : %s", type(error).__name__)
        raise DnsLookupError("request_failed") from None
    if response.status_code != 200:
        logger.warning("[control-tower dns] rejected : status %s", response.status_code)
        raise DnsLookupError(f"status_{response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise DnsLookupError("invalid_response") from None
    if not isinstance(body, dict) or body.get("success") is not True or not isinstance(body.get("result"), list):
        raise DnsLookupError("invalid_response")
    return body["result"]
