"""관제소 덮어쓰기: 저장소 왕복, 실효 등록 정보 병합(상태·숨김·순서·사용자 추가·id 충돌), Worker 스냅샷 확장"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from control_tower_admin_fixtures import REGISTRY, store  # noqa: F401 (pytest 픽스처 재노출)
from service.control_tower.override_models import CustomProject, CustomService
from service.control_tower.registry_overrides import apply_overrides

NOW = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)


def _custom_service(service_id: str, project_id: str = "elum", status: str = "active") -> CustomService:
    return CustomService(service_id, project_id, f"{service_id} 이름", f"https://{service_id}.example.com/",
                         status, True)


# ---- 저장소 ----

def test_서비스_덮어쓰기는_바뀐_칸만_저장하고_null은_지운다(store):
    store.save_service_override("elum-api", {"name": "새 이름", "is_public": False}, NOW)
    store.save_service_override("elum-api", {"sort_order": 3, "name": None}, NOW)

    override = store.load_registry_overrides().service_overrides["elum-api"]

    assert (override.name, override.is_public, override.sort_order) == (None, False, 3)
    assert override.overridden_fields() == ["is_public", "sort_order"]
    assert override.updated_at == NOW


def test_모든_칸을_지우면_덮어쓰기_행이_사라진다(store):
    store.save_project_override("elum", {"is_hidden": True}, NOW)
    store.save_project_override("elum", {"is_hidden": None}, NOW)

    assert store.load_registry_overrides().project_overrides == {}


def test_사용자_추가_서비스는_생성_순으로_읽고_삭제하면_덮어쓰기도_지운다(store):
    store.insert_custom_service(_custom_service("blog"), NOW)
    store.insert_custom_service(_custom_service("alpha"), NOW.replace(hour=4))
    store.save_service_override("blog", {"name": "블로그"}, NOW)

    assert [service.id for service in store.load_registry_overrides().custom_services] == ["blog", "alpha"]
    assert store.delete_custom_service("blog") is True
    assert store.delete_custom_service("blog") is False
    assert "blog" not in store.load_registry_overrides().service_overrides


def test_상태_페이지_설정은_기본값을_갖고_null이면_기본값으로_돌아간다(store):
    assert store.load_status_page().title == "SUHSAECHAN Status"
    store.save_status_page({"title": "내 상태", "notice_text": "점검 예정", "notice_level": "warning"})
    assert store.load_status_page().title == "내 상태"
    store.save_status_page({"title": None, "notice_level": None})

    page = store.load_status_page()
    assert (page.title, page.notice_text, page.notice_level) == ("SUHSAECHAN Status", "점검 예정", "info")


# ---- 병합 ----

def test_덮어쓰기가_없으면_등록_파일_그대로다(store):
    effective = apply_overrides(REGISTRY, store)

    assert effective.services == REGISTRY.services and effective.projects == REGISTRY.projects


@pytest.mark.parametrize("status", ["retired", "paused", "active"])
def test_상태_덮어쓰기는_감시_상태를_바꾼다(store, status):
    store.save_service_override("elum-web", {"status": status}, NOW)

    assert apply_overrides(REGISTRY, store).service_by_id("elum-web").status == status


def test_인프라는_이름_상태만_덮어쓰고_공개_외부_주소는_무시한다(store):
    store.save_service_override("nas", {"name": "NAS", "status": "paused", "is_public": True,
                                        "external_url": "https://nas.example.com/"}, NOW)

    nas = apply_overrides(REGISTRY, store).service_by_id("nas")

    assert (nas.name, nas.status, nas.is_public, nas.external) == ("NAS", "paused", False, None)


def test_외부_주소_덮어쓰기는_기대_코드와_제한_시간을_유지한다(store):
    store.save_service_override("elum-api", {"external_url": "https://new.example.com/"}, NOW)

    external = apply_overrides(REGISTRY, store).service_by_id("elum-api").external

    assert external.target == "https://new.example.com/" and external.kind == "http"


def test_숨긴_프로젝트의_서비스는_공개되지_않고_스냅샷_프로젝트에서도_빠진다(store):
    store.save_project_override("elum", {"is_hidden": True, "name": "이룸(숨김)"}, NOW)

    effective = apply_overrides(REGISTRY, store)
    snapshot = effective.to_worker_snapshot()

    assert effective.projects[0].is_hidden is True and effective.projects[0].name == "이룸(숨김)"
    assert effective.service_by_id("elum-api").is_public is False
    assert effective.service_by_id("elum-api").status == "active"  # 감시는 그대로
    assert snapshot["projects"] == []
    assert all(service["is_public"] is False for service in snapshot["services"])


def test_순서는_sort_order_있는_항목이_먼저이고_없는_항목은_원래_순서로_뒤에_온다(store):
    store.save_service_override("elum-web", {"sort_order": 0}, NOW)
    store.save_service_override("elum-batch", {"sort_order": 1}, NOW)

    effective = apply_overrides(REGISTRY, store)

    assert [service.id for service in effective.services] == ["elum-web", "elum-batch", "elum-api", "elum-old"]
    assert [service["order"] for service in effective.to_worker_snapshot()["services"]] == [0, 1, 2]


def test_사용자_추가_서비스는_외부_점검만_갖고_nas에_의존하며_파일_서비스_뒤에_온다(store):
    store.insert_custom_service(_custom_service("blog"), NOW)

    effective = apply_overrides(REGISTRY, store)
    blog = effective.service_by_id("blog")

    assert effective.services[-1].id == "blog"
    assert blog.internal is None and blog.external.target == "https://blog.example.com/"
    assert blog.depends_on == "nas" and blog.project_id == "elum"


def test_등록_파일과_id가_겹치거나_프로젝트가_없는_사용자_추가_서비스는_제외한다(store):
    store.insert_custom_service(_custom_service("elum-api"), NOW)
    store.insert_custom_service(_custom_service("orphan", project_id="gone"), NOW)

    effective = apply_overrides(REGISTRY, store)

    assert [service.id for service in effective.services].count("elum-api") == 1
    assert effective.service_by_id("elum-api").name == "이룸 API"
    assert effective.service_by_id("orphan") is None


def test_사용자_추가_프로젝트는_순서_덮어쓰기로_앞에_올_수_있다(store):
    store.insert_custom_project(CustomProject("blog", "블로그"), NOW)
    store.insert_custom_project(CustomProject("elum", "중복"), NOW)
    store.save_project_override("blog", {"sort_order": 0}, NOW)

    effective = apply_overrides(REGISTRY, store)

    assert [project.id for project in effective.projects] == ["blog", "elum"]
    assert effective.projects[1].name == "이룸"


# ---- 스냅샷 ----

def test_스냅샷은_page_공지와_order를_더하고_기존_필드를_유지한다(store):
    store.save_status_page({"title": "SUH 상태", "notice_text": "오늘 밤 점검", "notice_level": "critical"})

    effective = apply_overrides(REGISTRY, store)
    snapshot = effective.to_worker_snapshot()

    assert snapshot["page"] == {"title": "SUH 상태", "notice": {"text": "오늘 밤 점검", "level": "critical"}}
    assert snapshot["projects"] == [{"id": "elum", "name": "이룸", "order": 0}]
    assert set(snapshot["services"][0]) == {"id", "order", "name", "project_id", "status", "is_public", "external"}
    assert set(snapshot) == {"page", "alert", "projects", "services", "maintenance"}
    assert effective.version() != REGISTRY.version()


def test_공지가_비면_notice는_null이다():
    assert REGISTRY.to_worker_snapshot()["page"] == {"title": "SUHSAECHAN Status", "notice": None}
