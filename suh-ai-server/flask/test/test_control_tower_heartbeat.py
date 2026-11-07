"""관제소 심박 클라이언트: 서명 고정 벡터, 서명·본문 일치, need_config 재전송, 외부 결과 매핑, 실패 시 None"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pytest
import requests

from service.control_tower.check_runner import CheckResult
from service.control_tower.heartbeat_client import HeartbeatClient, HeartbeatResponse, sign
from service.control_tower.registry import CheckSpec, ProjectSpec, Registry, ServiceSpec

SECRET = "test-secret"
WORKER_URL = "https://worker.example.com/"
NOW = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)  # unix 1793750400
# hex(HMAC-SHA256('test-secret', '1793750400.{"a":1}')) — Worker 테스트와 같은 벡터
EXPECTED_VECTOR_SIGNATURE = "c21ffbba805fa20789178125ce878759ec5713384f5959d4230fcbbdd99614fc"

REGISTRY = Registry(
    projects=(ProjectSpec("elum", "이룸"),),
    services=(ServiceSpec("elum-api", "이룸 API", "elum", is_public=True,
                          external=CheckSpec("http", "https://api.elum.example.com/healthz", (200,))),),
)
PUBLIC_INCIDENTS = [{"service_id": "elum-api", "started_at": "2026-11-03T00:00:00+00:00", "ended_at": None}]
RESULTS_RESPONSE = {
    "need_config": False,
    "checked_at": "2026-11-03T23:59:30.000Z",
    "external_results": {
        "elum-api": {"is_ok": False, "is_slow": False, "status_code": 503, "latency_milliseconds": 87,
                     "error": None},
        "elum-web": {"is_ok": True, "is_slow": True, "status_code": 200, "latency_milliseconds": 6100,
                     "error": None},
        "broken": "not-a-mapping",
    },
}


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, is_json_valid: bool = True):
        self.status_code = status_code
        self._payload = payload
        self._is_json_valid = is_json_valid

    def json(self):
        if not self._is_json_valid:
            raise ValueError("bad json")
        return self._payload


class FakeSession:
    """요청 기록 + 준비된 응답 순서대로 반환 (예외 객체면 raise)"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.requests.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _client(*responses) -> tuple[HeartbeatClient, FakeSession]:
    session = FakeSession(*responses)
    return HeartbeatClient(WORKER_URL, SECRET, session=session), session


def test_서명은_고정_벡터와_일치한다():
    assert sign(SECRET, 1793750400, b'{"a":1}') == EXPECTED_VECTOR_SIGNATURE


def test_심박은_보낸_본문_바이트_그대로_서명하고_필수_필드를_담는다():
    client, session = _client(FakeResponse(payload=RESULTS_RESPONSE))

    client.send(REGISTRY, PUBLIC_INCIDENTS, NOW)

    sent = session.requests[0]
    assert sent["url"] == "https://worker.example.com/api/heartbeat"
    assert sent["timeout"] == 10
    assert sent["headers"]["X-CT-Timestamp"] == "1793750400"
    assert sent["headers"]["X-CT-Signature"] == sign(SECRET, 1793750400, sent["data"])
    assert b" " not in sent["data"]  # 공백 없는 직렬화
    body = json.loads(sent["data"])
    assert body == {"sent_at": NOW.isoformat(), "config_version": REGISTRY.version(),
                    "public_incidents": PUBLIC_INCIDENTS}


def test_한글_값은_이스케이프_없이_UTF8로_보낸다():
    client, session = _client(FakeResponse(payload={"need_config": True}), FakeResponse(payload=RESULTS_RESPONSE))

    client.send(REGISTRY, [], NOW)

    assert "이룸".encode("utf-8") in session.requests[1]["data"]
    assert b"\\u" not in session.requests[1]["data"]


def test_need_config면_스냅샷을_넣어_한_번만_다시_보낸다():
    client, session = _client(FakeResponse(payload={"need_config": True}), FakeResponse(payload=RESULTS_RESPONSE))

    response = client.send(REGISTRY, PUBLIC_INCIDENTS, NOW)

    assert len(session.requests) == 2
    first_body = json.loads(session.requests[0]["data"])
    second_body = json.loads(session.requests[1]["data"])
    assert "config" not in first_body
    assert second_body["config"] == REGISTRY.to_worker_snapshot()
    assert second_body["config_version"] == first_body["config_version"]
    assert session.requests[1]["headers"]["X-CT-Signature"] == sign(SECRET, 1793750400, session.requests[1]["data"])
    assert response is not None and "elum-api" in response.external_results


def test_재전송에도_need_config면_더_보내지_않고_외부_결과_없이_성공으로_본다():
    client, session = _client(FakeResponse(payload={"need_config": True}), FakeResponse(payload={"need_config": True}))

    response = client.send(REGISTRY, [], NOW)

    assert len(session.requests) == 2
    assert response == HeartbeatResponse(external_results={}, checked_at=None)


def test_외부_결과를_CheckResult로_바꾸고_시각은_응답_checked_at을_쓴다():
    client, _ = _client(FakeResponse(payload=RESULTS_RESPONSE))

    response = client.send(REGISTRY, [], NOW)

    checked_at = datetime(2026, 11, 3, 23, 59, 30, tzinfo=timezone.utc)
    assert response.checked_at == checked_at
    assert response.external_results == {
        "elum-api": CheckResult(False, False, 503, 87, None, checked_at),
        "elum-web": CheckResult(True, True, 200, 6100, None, checked_at),
    }


def test_checked_at이_없으면_외부_결과를_버린다():
    payload = {**RESULTS_RESPONSE, "checked_at": None}
    client, _ = _client(FakeResponse(payload=payload))

    response = client.send(REGISTRY, [], NOW)

    assert response == HeartbeatResponse(external_results={}, checked_at=None)


@pytest.mark.parametrize("response", [
    requests.exceptions.ConnectionError("refused test-secret"),
    requests.exceptions.Timeout("slow"),
    FakeResponse(status_code=401, payload={"error": "unauthorized"}),
    FakeResponse(status_code=500, payload=None),
    FakeResponse(is_json_valid=False),
    FakeResponse(payload=["not", "a", "mapping"]),
])
def test_실패는_None을_돌려주고_비밀키를_로그에_남기지_않는다(response, caplog):
    client, _ = _client(response)

    with caplog.at_level(logging.WARNING):
        assert client.send(REGISTRY, [], NOW) is None

    assert "[control-tower heartbeat]" in caplog.text
    assert SECRET not in caplog.text


def test_재전송이_실패하면_None이다():
    client, _ = _client(FakeResponse(payload={"need_config": True}), FakeResponse(status_code=503))

    assert client.send(REGISTRY, [], NOW) is None
