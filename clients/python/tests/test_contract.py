"""계약 테스트: 클라이언트 본문이 레포 스키마·예시와 일치하는지 확인"""
import json
from pathlib import Path

import pytest

from suh_control_tower import ControlTowerClient

EVENTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "control-tower" / "events"


def load_json(relative_path):
    return json.loads((EVENTS_DIR / relative_path).read_text(encoding="utf-8"))


def build_client_payload():
    client = ControlTowerClient(base_url="http://127.0.0.1:1", project="suh-ai", token="t")
    return client.build_payload(
        kind="claude-code", title="로그인 인증코드 발급", severity="info",
        fields=[("요청 경로", "메일 링크"), ("유효 시간", "10분")])


def test_payload_equals_example():
    assert build_client_payload() == load_json("examples/valid_custom_kind_fields.json")


def test_payload_satisfies_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(build_client_payload(), load_json("events-v1.schema.json"))
