"""관제소 프로젝트 썸네일: 저장소, 관리 API(업로드·주소·삭제), 관리 목록·스냅샷 반영, 기본 썸네일 채우기, 심박 동봉"""
from __future__ import annotations

import base64
import io
import json
from datetime import datetime, timezone

import pytest
from PIL import Image

from control_tower_admin_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    NOW, REGISTRY, FakePoller, _snapshot, dispatcher, make_app, store,
)
from service.control_tower import runtime as runtime_module
from service.control_tower.heartbeat_client import HeartbeatClient
from service.control_tower.project_icon_seed import seed_default_project_icons
from service.control_tower.project_icon_service import ProjectIconError, normalize_icon
from service.control_tower.registry import ProjectSpec, Registry
from service.control_tower.registry_overrides import apply_overrides
from service.control_tower.runtime import ControlTowerRuntime
from router import control_tower_icon_api

SAVED_AT = datetime(2026, 11, 8, tzinfo=timezone.utc)


def make_image_bytes(color=(200, 80, 20), size=(300, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def make_upload_payload(color=(200, 80, 20)) -> dict:
    return {"image_base64": base64.b64encode(make_image_bytes(color)).decode("ascii")}


@pytest.fixture
def icon_client(store, dispatcher):
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=FakePoller(_snapshot()), file_registry_provider=lambda: REGISTRY))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


# ---- 저장소 ----

def test_저장한_썸네일은_이미지와_버전으로_읽힌다(store):
    image_webp, content_hash = normalize_icon(make_image_bytes())

    store.save_project_icon("elum", image_webp, content_hash, SAVED_AT)

    assert store.load_project_icon_images() == {"elum": image_webp}
    assert store.load_project_icon_versions() == {"elum": content_hash}


def test_같은_프로젝트에_다시_저장하면_교체한다(store):
    first_webp, first_hash = normalize_icon(make_image_bytes((1, 2, 3)))
    second_webp, second_hash = normalize_icon(make_image_bytes((9, 9, 9)))

    store.save_project_icon("elum", first_webp, first_hash, SAVED_AT)
    store.save_project_icon("elum", second_webp, second_hash, SAVED_AT)

    assert store.load_project_icon_versions() == {"elum": second_hash}


def test_삭제는_지운_행이_있을_때만_true(store):
    image_webp, content_hash = normalize_icon(make_image_bytes())
    store.save_project_icon("elum", image_webp, content_hash, SAVED_AT)

    assert store.delete_project_icon("elum") is True
    assert store.delete_project_icon("elum") is False
    assert store.load_project_icon_images() == {}


# ---- 스냅샷·관리 목록 반영 ----

def test_썸네일_저장하면_스냅샷에_icon_version이_실려_스냅샷_버전이_바뀐다(store):
    registry_before = apply_overrides(REGISTRY, store)
    image_webp, content_hash = normalize_icon(make_image_bytes())
    store.save_project_icon("elum", image_webp, content_hash, SAVED_AT)

    registry_after = apply_overrides(REGISTRY, store)

    assert registry_before.to_worker_snapshot()["projects"][0]["icon_version"] is None
    assert registry_after.to_worker_snapshot()["projects"][0]["icon_version"] == content_hash
    assert registry_before.version() != registry_after.version()


def test_관리_목록은_썸네일을_data_url로_준다(icon_client, store):
    image_webp, content_hash = normalize_icon(make_image_bytes())
    store.save_project_icon("elum", image_webp, content_hash, SAVED_AT)

    project = icon_client.get("/control/manage").get_json()["projects"][0]

    assert project["icon_data_url"] == "data:image/webp;base64," + base64.b64encode(image_webp).decode("ascii")


# ---- PUT /control/projects/<id>/icon ----

def test_파일_업로드는_128px_webp로_저장되고_버전을_돌려준다(icon_client, store):
    response = icon_client.put("/control/projects/elum/icon", json=make_upload_payload())

    assert response.status_code == 200
    stored_image = Image.open(io.BytesIO(store.load_project_icon_images()["elum"]))
    assert stored_image.format == "WEBP" and stored_image.size == (128, 128)
    assert response.get_json()["content_hash"] == store.load_project_icon_versions()["elum"]


def test_주소_가져오기는_가져온_이미지를_저장한다(icon_client, store, monkeypatch):
    requested_urls = []

    def fake_fetch(url):
        requested_urls.append(url)
        return make_image_bytes()

    monkeypatch.setattr(control_tower_icon_api, "fetch_icon_bytes", fake_fetch)

    response = icon_client.put("/control/projects/elum/icon", json={"source_url": "https://lab.example.com/logo.png"})

    assert response.status_code == 200 and requested_urls == ["https://lab.example.com/logo.png"]
    assert "elum" in store.load_project_icon_versions()


@pytest.mark.parametrize("payload", [
    {}, {"image_base64": ""}, {"source_url": "http://lab.example.com/logo.png"}, {"source_url": "not a url"},
    {"image_base64": "AAAA", "source_url": "https://lab.example.com/logo.png"}, {"unknown": "x"}, [],
])
def test_잘못된_본문은_400(icon_client, store, payload):
    response = icon_client.put("/control/projects/elum/icon", json=payload)

    assert response.status_code == 400 and response.get_json()["error"] == "invalid"
    assert store.load_project_icon_versions() == {}


def test_알_수_없는_프로젝트는_404(icon_client):
    response = icon_client.put("/control/projects/nothing/icon", json=make_upload_payload())

    assert response.status_code == 404 and response.get_json()["error"] == "unknown_project"


@pytest.mark.parametrize("code, expected_status", [
    ("invalid_image", 400), ("image_too_large", 413), ("icon_fetch_failed", 502),
])
def test_이미지_오류는_코드별_상태로_돌려주고_저장하지_않는다(icon_client, store, monkeypatch, code, expected_status):
    def fail(url):
        raise ProjectIconError(code)

    monkeypatch.setattr(control_tower_icon_api, "fetch_icon_bytes", fail)

    response = icon_client.put("/control/projects/elum/icon", json={"source_url": "https://lab.example.com/logo.png"})

    assert response.status_code == expected_status and response.get_json()["error"] == code
    assert store.load_project_icon_versions() == {}


def test_이미지가_아닌_업로드는_400_invalid_image(icon_client):
    payload = {"image_base64": base64.b64encode(b"not an image").decode("ascii")}

    response = icon_client.put("/control/projects/elum/icon", json=payload)

    assert response.status_code == 400 and response.get_json()["error"] == "invalid_image"


def test_런타임이_없으면_503():
    runtime_module.set_runtime(None)
    client = make_app().test_client()

    assert client.put("/control/projects/elum/icon", json=make_upload_payload()).status_code == 503
    assert client.delete("/control/projects/elum/icon").status_code == 503


# ---- DELETE /control/projects/<id>/icon ----

def test_삭제하면_목록에서_썸네일이_사라진다(icon_client, store):
    icon_client.put("/control/projects/elum/icon", json=make_upload_payload())

    response = icon_client.delete("/control/projects/elum/icon")

    assert response.status_code == 200
    assert icon_client.get("/control/manage").get_json()["projects"][0]["icon_data_url"] is None


def test_썸네일이_없으면_삭제는_404(icon_client):
    response = icon_client.delete("/control/projects/elum/icon")

    assert response.status_code == 404 and response.get_json()["error"] == "no_icon"


# ---- 기본 썸네일 채우기 ----

SEED_REGISTRY = Registry(
    projects=(ProjectSpec("elum", "이룸", icon_source_url="https://lab.example.com/elum.png"),
              ProjectSpec("romrom", "롬롬"),
              ProjectSpec("passql", "패스큐일", icon_source_url="https://lab.example.com/passql.png")),
    services=(),
)


def fake_fetcher(requested_urls: list[str]):
    def fetch(url: str) -> bytes:
        requested_urls.append(url)
        return make_image_bytes()
    return fetch


def test_주소가_있는_프로젝트만_가져와_저장하고_완료를_표시한다(store):
    requested_urls: list[str] = []

    saved_count = seed_default_project_icons(SEED_REGISTRY, store, fake_fetcher(requested_urls))

    assert saved_count == 2 and sorted(requested_urls) == [
        "https://lab.example.com/elum.png", "https://lab.example.com/passql.png"]
    assert sorted(store.load_project_icon_versions()) == ["elum", "passql"]
    assert store.has_icon_seed_finished("elum") and not store.has_icon_seed_finished("romrom")


def test_두_번째_실행은_다시_가져오지_않는다(store):
    seed_default_project_icons(SEED_REGISTRY, store, fake_fetcher([]))
    requested_urls: list[str] = []

    saved_count = seed_default_project_icons(SEED_REGISTRY, store, fake_fetcher(requested_urls))

    assert saved_count == 0 and requested_urls == []


def test_관리_화면에서_삭제한_썸네일은_다시_채우지_않는다(store):
    seed_default_project_icons(SEED_REGISTRY, store, fake_fetcher([]))
    store.delete_project_icon("elum")
    requested_urls: list[str] = []

    seed_default_project_icons(SEED_REGISTRY, store, fake_fetcher(requested_urls))

    assert "elum" not in store.load_project_icon_versions() and requested_urls == []


def test_이미_올린_썸네일이_있으면_덮어쓰지_않고_완료만_표시한다(store):
    image_webp, content_hash = normalize_icon(make_image_bytes((1, 1, 1)))
    store.save_project_icon("elum", image_webp, content_hash, SAVED_AT)
    requested_urls: list[str] = []

    seed_default_project_icons(SEED_REGISTRY, store, fake_fetcher(requested_urls))

    assert store.load_project_icon_versions()["elum"] == content_hash
    assert "https://lab.example.com/elum.png" not in requested_urls and store.has_icon_seed_finished("elum")


def test_가져오기_실패는_완료_표시를_남기지_않아_다음_기동에_재시도한다(store):
    def failing_fetch(url: str) -> bytes:
        raise ProjectIconError("icon_fetch_failed")

    saved_count = seed_default_project_icons(SEED_REGISTRY, store, failing_fetch)

    assert saved_count == 0 and not store.has_icon_seed_finished("elum")
    assert store.load_project_icon_versions() == {}


# ---- 심박 동봉 ----

class RecordingSession:
    def __init__(self):
        self.bodies: list[dict] = []
        self._responses = [{"need_config": True}, {"need_config": False, "checked_at": None, "external_results": {}}]

    def post(self, url, data=None, headers=None, timeout=None):
        self.bodies.append(json.loads(data))
        payload = self._responses.pop(0)

        class Response:
            status_code = 200

            def json(self):
                return payload
        return Response()


def test_스냅샷을_실을_때만_썸네일을_base64로_동봉한다():
    session = RecordingSession()
    client = HeartbeatClient("https://worker.example.com", "secret", session=session)

    client.send(REGISTRY, [], NOW, project_icons={"elum": b"webp-bytes"})

    first_body, resent_body = session.bodies
    assert "project_icons" not in first_body and "config" not in first_body
    assert resent_body["project_icons"] == {"elum": base64.b64encode(b"webp-bytes").decode("ascii")}
    assert "config" in resent_body
