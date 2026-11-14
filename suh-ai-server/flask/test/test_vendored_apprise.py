"""test_vendored_apprise.py — 벤더링한 Apprise(vendor.apprise) 로드·URL 해석·로컬 발송 검증"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from vendor.apprise import Apprise, NotifyFormat

LOCAL_HOST = '127.0.0.1'


class _RecordingHandler(BaseHTTPRequestHandler):
    """받은 POST 본문을 서버 객체에 쌓는 가짜 수신기"""

    def do_POST(self):
        body_length = int(self.headers.get('Content-Length', 0))
        self.server.received_bodies.append(self.rfile.read(body_length))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def local_receiver():
    """127.0.0.1 임의 포트 HTTP 서버 (외부 네트워크 사용 안 함)"""
    server = HTTPServer((LOCAL_HOST, 0), _RecordingHandler)
    server.received_bodies = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_vendored_apprise_imports():
    assert Apprise is not None
    assert NotifyFormat.TEXT


def test_vendored_apprise_parses_discord_url():
    assert Apprise.instantiate('discord://1234/abcd') is not None


def test_vendored_apprise_rejects_garbage():
    assert Apprise.instantiate('nope://x') is None


def test_vendored_apprise_plugins_load_under_vendor_package():
    from vendor.apprise.manager_plugins import NotificationManager
    manager = NotificationManager()
    assert manager.module_name_prefix == 'vendor.apprise.plugins'
    assert len(manager.schemas()) > 50


def test_vendored_apprise_json_notify(local_receiver):
    port = local_receiver.server_address[1]
    apprise_client = Apprise()
    assert apprise_client.add(f'json://{LOCAL_HOST}:{port}/hook')
    assert bool(apprise_client.notify(title='제목', body='본문'))
    assert len(local_receiver.received_bodies) == 1
    payload = json.loads(local_receiver.received_bodies[0])
    assert payload['message'] == '본문'
    assert payload['title'] == '제목'
