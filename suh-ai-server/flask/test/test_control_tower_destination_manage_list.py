"""관제소 받을 곳 관리 목록: 프로젝트별 힌트만, 입력 규칙·결과 문구 원본, URL 원문 노출 없음, 비밀값 없어도 열림"""
from __future__ import annotations

import logging
from unittest.mock import patch

from control_tower_admin_fixtures import dispatcher, store  # noqa: F401 (pytest 픽스처 재노출)
from control_tower_destination_api_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    CREATE_PATH, DISCORD_URL, SECRET_VALUE, WEBHOOK_TOKEN, _create, _manage_destinations, destination_client,
    fake_apprise_sends, fast_kdf,
)
from service.control_tower import destination_delivery
from service.control_tower.destination_validation import (
    DESTINATION_ERROR_RESULT_LABEL, DESTINATION_LABEL_MAX_LENGTH, DESTINATION_RESULT_LABELS, DESTINATION_URL_MAX_LENGTH,
)


def test_관리_목록에_프로젝트별_받을_곳이_힌트만으로_실린다(destination_client):
    destination_id = _create(destination_client).get_json()["destination_id"]

    destinations = _manage_destinations(destination_client)

    assert destinations == [{"destination_id": destination_id, "kind": "error", "label": "팀 디스코드",
                             "url_hint": "discord://…zz99", "is_enabled": True, "last_result": None,
                             "last_sent_at": None}]


def test_관리_목록의_받을_곳_규칙은_검증_상수와_결과_문구_원본과_같다(destination_client):
    body = destination_client.get("/control/manage").get_json()

    assert body["destination_options"] == {
        "label_max_length": DESTINATION_LABEL_MAX_LENGTH, "url_max_length": DESTINATION_URL_MAX_LENGTH,
        "result_labels": DESTINATION_RESULT_LABELS, "error_result_prefix": destination_delivery.RESULT_ERROR_PREFIX,
        "error_result_label": DESTINATION_ERROR_RESULT_LABEL}
    assert set(DESTINATION_RESULT_LABELS) == {
        destination_delivery.RESULT_SENT, destination_delivery.RESULT_FAILED,
        destination_delivery.RESULT_SECRET_MISSING, destination_delivery.RESULT_DECRYPT_FAILED}


def test_URL_원문이_관리_목록_감사_로그_오류_응답에_없다(destination_client, caplog, fake_apprise_sends):
    caplog.set_level(logging.DEBUG)
    with patch("util.audit_helper.audit_service.record") as record:
        destination_id = _create(destination_client).get_json()["destination_id"]
        destination_client.post(f"/control/destinations/{destination_id}/test")
        invalid_text = destination_client.post(
            CREATE_PATH, json={"kind": "nope", "label": "팀", "url": DISCORD_URL}).get_data(as_text=True)
        destination_client.delete(f"/control/destinations/{destination_id}")
        _create(destination_client)

    manage_text = destination_client.get("/control/manage").get_data(as_text=True)
    exposed_text = manage_text + repr(record.call_args_list) + caplog.text + invalid_text
    assert WEBHOOK_TOKEN not in exposed_text
    assert SECRET_VALUE not in exposed_text


def test_비밀값이_없어도_관리_목록은_열린다(destination_client, monkeypatch):
    _create(destination_client)
    monkeypatch.delenv("CONTROL_TOWER_SECRET")

    body = destination_client.get("/control/manage").get_json()

    assert body["is_token_secret_configured"] is False
    assert len(next(project for project in body["projects"] if project["id"] == "elum")["destinations"]) == 1
