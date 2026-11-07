"""관제소 Cloudflare DNS 후보: 등록 호스트 제외·종류 필터·중복 제거, 토큰 없음 503, 조회 실패 502 (HTTP는 가짜)"""
from __future__ import annotations

import pytest
import requests

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    REGISTRY, FakePoller, _snapshot, dispatcher, make_app, store,
)
from service.control_tower import dns_candidates, runtime as runtime_module
from service.control_tower.dns_candidates import DnsLookupError, fetch_dns_candidates, registered_hosts
from service.control_tower.runtime import ControlTowerRuntime

ZONE_ID = "zone-1"
RECORDS = [
    {"name": "api.example.com", "type": "A", "proxied": True},  # 등록됨 (elum-api)
    {"name": "blog.suhsaechan.kr", "type": "CNAME", "proxied": True},
    {"name": "blog.suhsaechan.kr", "type": "AAAA", "proxied": False},  # 같은 이름 중복
    {"name": "Admin.suhsaechan.kr", "type": "A", "proxied": False},
    {"name": "*.suhsaechan.kr", "type": "A"},  # 와일드카드
    {"name": "suhsaechan.kr", "type": "MX"},  # 종류 제외
    {"name": "_acme.suhsaechan.kr", "type": "TXT"},
]


class FakeResponse:
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, zones=None, records=None, status_code: int = 200, error: Exception | None = None):
        self.zones = [{"id": ZONE_ID}] if zones is None else zones
        self.records = RECORDS if records is None else records
        self.status_code = status_code
        self.error = error
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if self.error is not None:
            raise self.error
        result = self.records if url.endswith("/dns_records") else self.zones
        return FakeResponse(self.status_code, {"success": True, "result": result})


def test_후보는_등록된_호스트_와일드카드_다른_종류를_빼고_이름당_1건이다():
    session = FakeSession()

    candidates = fetch_dns_candidates("token-x", "suhsaechan.kr", registered_hosts(REGISTRY), session)

    assert candidates == [
        {"hostname": "admin.suhsaechan.kr", "type": "A", "is_proxied": False},
        {"hostname": "blog.suhsaechan.kr", "type": "CNAME", "is_proxied": True},
    ]
    zone_call, records_call = session.calls
    assert zone_call[1] == {"name": "suhsaechan.kr"} and zone_call[2] == {"Authorization": "Bearer token-x"}
    assert records_call[0].endswith(f"/zones/{ZONE_ID}/dns_records") and records_call[1] == {"per_page": 500}


def test_registered_hosts는_외부_점검_주소_호스트만_소문자로():
    assert registered_hosts(REGISTRY) == {"api.example.com"}


@pytest.mark.parametrize("session, reason", [
    (FakeSession(zones=[]), "zone_not_found"),
    (FakeSession(status_code=403), "status_403"),
    (FakeSession(error=requests.ConnectionError("boom")), "request_failed"),
])
def test_조회_실패는_사유_코드와_함께_DnsLookupError(session, reason):
    with pytest.raises(DnsLookupError) as raised:
        fetch_dns_candidates("token-x", "suhsaechan.kr", set(), session)

    assert raised.value.reason == reason


@pytest.fixture
def dns_client(store, dispatcher):
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=FakePoller(_snapshot()), file_registry_provider=lambda: REGISTRY))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


def test_토큰이_없으면_503과_사유(dns_client, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)

    response = dns_client.get("/control/dns-candidates")

    assert response.status_code == 503 and response.get_json()["error"] == "cloudflare_not_configured"


def test_API는_실효_등록_정보의_호스트를_빼고_후보를_준다(dns_client, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-secret")
    monkeypatch.delenv("CLOUDFLARE_ZONE_NAME", raising=False)
    dns_client.post("/control/services", json={"id": "blog", "project_id": "elum", "name": "블로그",
                                               "external_url": "https://blog.suhsaechan.kr/"})
    monkeypatch.setattr(dns_candidates, "requests", _RequestsModule(FakeSession()))

    body = dns_client.get("/control/dns-candidates").get_json()

    assert body["zone"] == "suhsaechan.kr"
    assert [candidate["hostname"] for candidate in body["candidates"]] == ["admin.suhsaechan.kr"]
    assert "token-secret" not in str(body)


def test_API_조회_실패는_502(dns_client, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-secret")
    monkeypatch.setattr(dns_candidates, "requests", _RequestsModule(FakeSession(status_code=500)))

    response = dns_client.get("/control/dns-candidates")

    assert response.status_code == 502 and response.get_json()["reason"] == "status_500"


class _RequestsModule:
    """requests 모듈 대역: get만 가짜 세션으로, 예외 종류는 진짜"""
    RequestException = requests.RequestException

    def __init__(self, session: FakeSession):
        self.get = session.get
