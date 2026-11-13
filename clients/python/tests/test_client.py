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
                    for name, value in getattr(outer, "extra_headers", {}).items():
                        self.send_header(name, value)
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


@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (404, "unknown_project"),
                                         (503, "unavailable"), (400, "invalid")])
def test_server_error_codes(make_server, status, code):
    server = make_server(status=status, response_body={"error": code})
    result = make_client(server).notify("report", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, status, code)


def test_non_202_success_is_not_accepted(make_server):
    server = make_server(status=200, response_body={"accepted": True})
    result = make_client(server).notify("report", "제목")
    assert (result.is_accepted, result.status_code) == (False, 200)


def test_redirect_not_followed_and_token_not_forwarded(make_server):
    target = make_server()
    redirector = make_server(status=302)
    redirector.extra_headers = {"Location": target.base_url + "/control/events"}
    result = make_client(redirector).notify("report", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, 302, "http_302")
    assert target.received_requests == []


def test_none_field_value_is_invalid_input(make_server):
    server = make_server()
    result = make_client(server).notify("report", "t", fields={"a": None})
    assert (result.is_accepted, result.error_code) == (False, "invalid_input")
    assert server.received_requests == []


@pytest.mark.parametrize("kwargs", [
    {"project": "", "token": "t"}, {"project": "p", "token": ""},
    {"project": "p", "token": "a b"}, {"project": "p", "token": "a\nb"},
    {"project": "p", "token": "토큰"},
    {"project": "p", "token": "t", "base_url": "http://example.com"},
    {"project": "p", "token": "t", "base_url": "ftp://x"},
])
def test_bad_configuration_raises_value_error(kwargs):
    with pytest.raises(ValueError) as error_info:
        ControlTowerClient(**kwargs)
    # 설정 오류 메시지에 토큰 값이 들어가지 않음 (길이 있는 토큰만 검사)
    if len(kwargs["token"]) > 1:
        assert kwargs["token"] not in str(error_info.value)


def test_https_and_localhost_base_urls_accepted():
    ControlTowerClient(project="p", token="t")
    ControlTowerClient(project="p", token="t", base_url="http://localhost:8080")


def test_init_requires_keywords():
    with pytest.raises(TypeError):
        suh_control_tower.init("https://x.y", "p", "t")


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
    suh_control_tower._reset_for_test()
    result = suh_control_tower.notify("report", "제목")
    assert (result.is_accepted, result.status_code, result.error_code) == (False, None, "not_initialized")


def test_module_level_init_and_notify(make_server):
    server = make_server()
    suh_control_tower.init(base_url=server.base_url, project="suh-ai", token="secret-token-123")
    assert suh_control_tower.notify("report", "제목").is_accepted
    suh_control_tower._reset_for_test()


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


def test_notify_in_background_returns_before_response(make_server):
    release = threading.Event()
    server = make_server()
    original_sleep_free = server.httpd.RequestHandlerClass

    class BlockingHandler(original_sleep_free):
        def do_POST(self):
            release.wait(5)
            super().do_POST()

    server.httpd.RequestHandlerClass = BlockingHandler
    thread = make_client(server, timeout_seconds=10).notify_in_background("report", "t")
    # 서버가 응답을 막고 있는 동안에도 호출이 반환됐고 전송은 아직 끝나지 않음
    assert thread.is_alive() and thread.daemon
    release.set()
    thread.join(5)
    assert len(server.received_requests) == 1


def test_module_level_notify_in_background(make_server):
    server = make_server()
    suh_control_tower.init(base_url=server.base_url, project="suh-ai", token="secret-token-123")
    thread = suh_control_tower.notify_in_background("report", "t", severity="warning")
    thread.join(5)
    suh_control_tower._reset_for_test()
    assert json.loads(server.received_requests[0][2])["severity"] == "warning"


def test_module_level_notify_in_background_before_init_returns_none():
    suh_control_tower._reset_for_test()
    assert suh_control_tower.notify_in_background("report", "t") is None
