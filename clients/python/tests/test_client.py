"""클라이언트 동작 테스트: 로컬 127.0.0.1 http.server만 사용"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import suh_control_tower
from suh_control_tower import ControlTowerClient, NotifyResult


class FakeServer:
    """응답 상태·본문·지연을 지정하고 받은 요청을 기록하는 테스트 서버"""

    def __init__(self, status=202, response_body=None, delay_seconds=0.0):
        self.received_requests = []
        outer = self
        self.status = status
        self.response_body = response_body if response_body is not None else {"accepted": True, "deduplicated": False}
        self.delay_seconds = delay_seconds

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                outer.received_requests.append((self.path, dict(self.headers), raw))
                time.sleep(outer.delay_seconds)
                payload = outer.response_body
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                try:
                    self.send_response(outer.status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = "http://127.0.0.1:%d" % self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def make_server():
    servers = []

    def factory(**kwargs):
        server = FakeServer(**kwargs)
        servers.append(server)
        return server

    yield factory
    for server in servers:
        server.close()


def make_client(server, **kwargs):
    return ControlTowerClient(base_url=server.base_url, project="suh-ai", token="secret-token-123", **kwargs)


def test_accepted(make_server):
    server = make_server()
    result = make_client(server).notify("report", "제목")
    assert result == NotifyResult(is_accepted=True, status_code=202, error_code=None, is_deduplicated=False)
    assert server.received_requests[0][0] == "/control/events"


def test_deduplicated(make_server):
    server = make_server(response_body={"accepted": True, "deduplicated": True})
    result = make_client(server).notify("report", "제목", dedupe_key="k")
    assert result.is_accepted and result.is_deduplicated


def test_unknown_kind(make_server):
    server = make_server(status=400, response_body={"error": "unknown_kind", "kind": "x"})
    result = make_client(server).notify("x", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, 400, "unknown_kind")


def test_unauthorized_and_unknown_project_and_unavailable(make_server):
    for status, code in [(401, "unauthorized"), (404, "unknown_project"), (503, "unavailable")]:
        server = make_server(status=status, response_body={"error": code})
        result = make_client(server).notify("report", "제목")
        assert (result.status_code, result.error_code) == (status, code)


def test_non_json_error_uses_http_status(make_server):
    server = make_server(status=413, response_body=b"<html>too large</html>")
    result = make_client(server).notify("report", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, 413, "http_413")


def test_timeout(make_server):
    server = make_server(delay_seconds=1.0)
    result = make_client(server, timeout_seconds=0.2).notify("report", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, None, "timeout")


def test_connection_refused():
    client = ControlTowerClient(base_url="http://127.0.0.1:1", project="p", token="t", timeout_seconds=1)
    result = client.notify("report", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, None, "connection_error")


def test_not_initialized():
    suh_control_tower.reset()
    result = suh_control_tower.notify("report", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, None, "not_initialized")


def test_module_level_init_and_notify(make_server):
    server = make_server()
    suh_control_tower.init(server.base_url, "suh-ai", "secret-token-123")
    assert suh_control_tower.notify("report", "제목").is_accepted
    suh_control_tower.reset()


def test_korean_body_sent_as_utf8_and_header(make_server):
    server = make_server()
    make_client(server).notify("report", "한글 제목", body="본문", fields={"요청 경로": "메일 링크"}, url="https://a.b")
    _, headers, raw = server.received_requests[0]
    assert "한글 제목".encode("utf-8") in raw
    assert headers["X-Control-Token"] == "secret-token-123"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(raw)["fields"] == [{"name": "요청 경로", "value": "메일 링크"}]


def test_fields_accepts_pairs_and_keeps_order(make_server):
    server = make_server()
    make_client(server).notify("report", "t", fields=[("b", "1"), ("a", 2)])
    fields = json.loads(server.received_requests[0][2])["fields"]
    assert fields == [{"name": "b", "value": "1"}, {"name": "a", "value": "2"}]


def test_optional_fields_omitted(make_server):
    server = make_server()
    make_client(server).notify("report", "t")
    assert json.loads(server.received_requests[0][2]) == {
        "project": "suh-ai", "kind": "report", "severity": "info", "title": "t"}


def test_repr_has_no_token(make_server):
    server = make_server()
    assert "secret-token-123" not in repr(make_client(server))
    assert "secret-token-123" not in str(make_client(server))


def test_notify_in_background_returns_immediately(make_server):
    server = make_server(delay_seconds=1.0)
    client = make_client(server, timeout_seconds=3)
    started = time.monotonic()
    thread = client.notify_in_background("report", "t")
    assert time.monotonic() - started < 0.5
    thread.join(5)
    assert len(server.received_requests) == 1
