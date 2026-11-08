"""앱 확인할 일 API 테스트 공통: 처리기를 심은 런타임 Flask 클라이언트, 소스 저장, 스냅샷 본문"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from control_tower_admin_fixtures import REGISTRY, FakePoller, _snapshot
from service.control_tower import runtime as runtime_module
from service.control_tower.app_attention_fetch import FetchOutcome
from service.control_tower.app_attention_ingest import AppAttentionIngest
from service.control_tower.app_attention_store import AttentionSource
from service.control_tower.runtime import ControlTowerRuntime

BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ingest(store, dispatcher) -> AppAttentionIngest:
    return AppAttentionIngest(store, dispatcher, lambda: REGISTRY, lambda project_id: False)


@pytest.fixture
def attention_client(store, dispatcher, ingest):
    from control_tower_admin_fixtures import make_app
    runtime_module.set_runtime(ControlTowerRuntime(
        lambda: REGISTRY, store, dispatcher, poller=FakePoller(_snapshot()), file_registry_provider=lambda: REGISTRY,
        app_attention_ingest=ingest))
    yield make_app().test_client()
    runtime_module.set_runtime(None)


def save_source(store, source_id: str = "api", mode: str = "both", is_enabled: bool = True) -> AttentionSource:
    source = AttentionSource("elum", source_id, "https://elum.example/attention", is_enabled, mode, 60, 5, 300,
                             BASE_TIME, BASE_TIME)
    store.save_attention_source(source)
    return source


def feedback_item(count: int = 3, total: int = 10, **fields) -> dict:
    return {"key": "feedback.new", "label": "새 의견", "kind": "count", "count": count, "total": total,
            "level": "info", **fields}


def snapshot_document(minutes: int = 0, items=None) -> dict:
    return {"schema": "attention", "version": "1.0",
            "source": {"app": "elum-server", "app_version": "2.3.1", "environment": "production"},
            "generated_at": (BASE_TIME + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
            "items": [feedback_item()] if items is None else items}


def ingest_snapshot(ingest, source: AttentionSource, minutes: int = 0, items=None):
    """pull 결과 1건 반영 (첫 반영은 기준선)"""
    return ingest.ingest(source, FetchOutcome("ok", snapshot_document(minutes, items), None, None),
                         BASE_TIME + timedelta(minutes=minutes))
