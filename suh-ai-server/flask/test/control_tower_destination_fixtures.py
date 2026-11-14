"""관제소 받을 곳 테스트 공통: 비밀값·URL 상수, 즉시 실행기, 로컬 수신 서버, 저장소, 가짜 디스코드, 알림·받을 곳 생성"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from service import secret_cipher
from service.control_tower.alert_planner import Notification
from service.control_tower.destination_delivery import describe_url_hint, encrypt_destination_url
from service.control_tower.store import ControlTowerStore

NOW = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
SECRET_ENVIRON = {"CONTROL_TOWER_SECRET": "tower-secret"}
OTHER_SECRET_ENVIRON = {"CONTROL_TOWER_SECRET": "other-secret"}
DISCORD_TOKEN = "webhook-token-value-ab12"
DISCORD_URL = f"discord://1234567890/{DISCORD_TOKEN}"
LOCAL_HOST = "127.0.0.1"


def _run_now(task, thread_name):
    task()


class _RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body_length = int(self.headers.get("Content-Length", 0))
        self.server.received_bodies.append((self.path, self.rfile.read(body_length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    # 테스트 속도: 반복 횟수만 낮춤 (알고리즘 동일)
    monkeypatch.setattr(secret_cipher, "PBKDF2_ITERATIONS", 1000)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


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


class FakeDiscordClient:
    def __init__(self):
        self.sent = []

    def send_embed(self, channel_id, embed):
        self.sent.append((channel_id, embed))
        return True


class FakeBindingStore:
    def get_binding(self, scope, kind):
        return f"channel-{scope}-{kind}"


def _notification(scope="elum", kind="report", **overrides) -> Notification:
    fields = dict(scope=scope, kind=kind, severity="warning", title="신고 접수", body="신고 123번", service_ids=(),
                  dedupe_key="", link_url="https://elum.example.com/reports/123", fields=(("사유", "스팸"),))
    fields.update(overrides)
    return Notification(**fields)


def _add_destination(store, project_id, kind, url, is_enabled=True, environ=SECRET_ENVIRON) -> int:
    url_encrypted, scheme = encrypt_destination_url(url, environ)
    destination_id = store.insert_destination(project_id, kind, f"{project_id} {kind}", url_encrypted, scheme,
                                              describe_url_hint(url), NOW)
    if not is_enabled:
        store.set_destination_enabled(destination_id, False)
    return destination_id


def _all_stored_text(store) -> str:
    connection = store._connection()
    table_names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    rows = [tuple(row) for name in table_names for row in connection.execute(f'SELECT * FROM "{name}"')]
    return repr(rows)


def _results_by_id(store) -> dict[int, str | None]:
    return {destination.destination_id: destination.last_result for destination in store.list_destinations()}


