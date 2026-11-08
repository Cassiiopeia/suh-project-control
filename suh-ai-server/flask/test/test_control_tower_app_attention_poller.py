"""앱 확인할 일 폴러 단계: 수집 시점, push 전용 연동 판정, 틱 예산, 예외 격리, 폴러 연결"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from service.control_tower.app_attention_fetch import FetchOutcome
from service.control_tower.app_attention_ingest import AppAttentionIngest
from service.control_tower.app_attention_store import AttentionSource
from service.control_tower.poller_app_attention import AppAttentionStep, is_any_project_service_down
from service.control_tower.poller import ControlTowerPoller
from service.control_tower.registry import Registry
from service.control_tower.registry_models import ServiceSpec
from service.control_tower.state_machine import INITIAL_STATE
from service.control_tower.store import ControlTowerStore
from control_tower_discord_fakes import ELUM, make_registry
from control_tower_poller_fixtures import (
    FakeCheckRunner, FakeClock, FakeDispatcher, make_poller, registry_path, run_ticks,  # noqa: F401
)

BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


@pytest.fixture
def dispatcher():
    return FakeDispatcher()


def _save_source(store, source_id="api", mode="pull", interval=60, stale_after=300, is_enabled=True):
    source = AttentionSource("elum", source_id, "https://elum.example/attention", is_enabled, mode, interval, 5,
                             stale_after, BASE_TIME, BASE_TIME)
    store.save_attention_source(source)
    return source


def _ok_outcome(minutes: int = 0, poll_after_seconds=None) -> FetchOutcome:
    document = {"schema": "attention", "version": "1.0",
                "source": {"app": "elum-server", "app_version": "1", "environment": "production"},
                "generated_at": (BASE_TIME + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
                "items": []}
    if poll_after_seconds is not None:
        document["poll_after_seconds"] = poll_after_seconds
    return FetchOutcome("ok", document, None, None)


class RecordingFetch:
    """호출 기록 + 소스별 지연·결과 지정"""

    def __init__(self, delay_seconds_by_source=None, outcome_factory=lambda source: _ok_outcome()):
        self.called_source_ids: list[str] = []
        self.delay_seconds_by_source = delay_seconds_by_source or {}
        self.outcome_factory = outcome_factory
        self._guard = threading.Lock()

    def __call__(self, source, etag):
        with self._guard:
            self.called_source_ids.append(source.source_id)
        time.sleep(self.delay_seconds_by_source.get(source.source_id, 0))
        return self.outcome_factory(source)


def _step(store, dispatcher, fetch, **options) -> AppAttentionStep:
    registry = make_registry(ELUM)
    ingest = AppAttentionIngest(store, dispatcher, lambda: registry, lambda project_id: False)
    return AppAttentionStep(store, ingest, fetch=fetch, **options)


def _at(seconds: float) -> datetime:
    return BASE_TIME + timedelta(seconds=seconds)


def test_주기_전에는_수집하지_않고_주기_5초_전부터_수집한다(store, dispatcher):
    _save_source(store, interval=60)
    fetch = RecordingFetch()
    step = _step(store, dispatcher, fetch)
    step.run(_at(0))
    step.run(_at(30))
    step.run(_at(54))
    assert fetch.called_source_ids == ["api"]
    step.run(_at(55))
    assert fetch.called_source_ids == ["api", "api"]


def test_앱이_요청한_다음_수집_시각이_있으면_interval보다_그_시각을_따른다(store, dispatcher):
    _save_source(store, interval=60)
    fetch = RecordingFetch(outcome_factory=lambda source: _ok_outcome(poll_after_seconds=600))
    step = _step(store, dispatcher, fetch)
    step.run(_at(0))
    step.run(_at(120))
    step.run(_at(594))
    assert fetch.called_source_ids == ["api"]
    step.run(_at(595))
    assert fetch.called_source_ids == ["api", "api"]


def test_push_전용과_꺼진_소스는_수집하지_않는다(store, dispatcher):
    _save_source(store, "pushed", mode="push")
    _save_source(store, "off", is_enabled=False)
    _save_source(store, "both", mode="both")
    fetch = RecordingFetch()
    _step(store, dispatcher, fetch).run(_at(0))
    assert fetch.called_source_ids == ["both"]


def test_push_전용_소스도_마지막_성공이_오래되면_끊김을_매_틱_판정해_한_번만_알린다(store, dispatcher):
    _save_source(store, "pushed", mode="push", interval=300, stale_after=1500)
    step = _step(store, dispatcher, RecordingFetch())
    step.run(_at(600))
    assert dispatcher.notifications == []
    step.run(_at(1501))
    step.run(_at(1561))
    assert len(dispatcher.notifications) == 1
    assert store.get_attention_source_state("elum", "pushed").failure_alerted_at == _at(1501)


def test_수집한_소스는_단계에서_연동_판정을_다시_부르지_않는다(store):
    _save_source(store, "api")
    _save_source(store, "pushed", mode="push")

    class RecordingIngest:
        def __init__(self):
            self.ingested, self.health_checked = [], []

        def ingest(self, source, outcome, now):
            self.ingested.append(source.source_id)

        def check_source_health(self, source, now):
            self.health_checked.append(source.source_id)

    ingest = RecordingIngest()
    AppAttentionStep(store, ingest, fetch=RecordingFetch()).run(_at(0))
    assert (ingest.ingested, ingest.health_checked) == (["api"], ["pushed"])


def test_한_소스가_느려도_run은_틱_예산_근처에서_반환하고_다른_소스는_처리된다(store, dispatcher):
    _save_source(store, "slow")
    _save_source(store, "fast")
    fetch = RecordingFetch(delay_seconds_by_source={"slow": 2.0})
    step = _step(store, dispatcher, fetch, tick_budget_seconds=0.5)
    started = time.monotonic()
    step.run(_at(0))
    elapsed = time.monotonic() - started
    assert elapsed < 1.5
    fast_state = store.get_attention_source_state("elum", "fast")
    slow_state = store.get_attention_source_state("elum", "slow")
    assert fast_state.last_result == "ok" and fast_state.consecutive_failures == 0
    assert (slow_state.last_result, slow_state.last_error, slow_state.consecutive_failures) == (
        "timeout", "tick_budget", 1)
    assert slow_state.last_attempt_at == _at(0)


def test_일꾼보다_소스가_많아_시작하지_못한_수집은_실패로_기록하지_않고_다음_틱에_맡긴다(store, dispatcher):
    _save_source(store, "first")
    _save_source(store, "second")
    fetch = RecordingFetch(delay_seconds_by_source={"first": 1.0, "second": 1.0})
    step = _step(store, dispatcher, fetch, max_workers=1, tick_budget_seconds=0.3)
    step.run(_at(0))
    queued_ids = [source_id for source_id in ("first", "second")
                  if store.get_attention_source_state("elum", source_id) is None]
    assert len(queued_ids) == 1
    assert fetch.called_source_ids and queued_ids[0] not in fetch.called_source_ids


def test_수집_함수가_예외를_던져도_틱_밖으로_나가지_않고_그_소스만_실패로_기록한다(store, dispatcher):
    _save_source(store, "broken")
    _save_source(store, "fine")

    def fetch(source, etag):
        if source.source_id == "broken":
            raise RuntimeError("boom")
        return _ok_outcome()

    _step(store, dispatcher, fetch).run(_at(0))
    assert store.get_attention_source_state("elum", "broken").last_result == "error"
    assert store.get_attention_source_state("elum", "fine").last_result == "ok"


def test_처리기와_저장소가_예외를_던져도_run은_예외를_내보내지_않는다(store):
    _save_source(store)

    class ExplodingIngest:
        def ingest(self, source, outcome, now):
            raise RuntimeError("ingest exploded")

        def check_source_health(self, source, now):
            raise RuntimeError("health exploded")

    AppAttentionStep(store, ExplodingIngest(), fetch=RecordingFetch()).run(_at(0))

    class BrokenStore:
        def list_attention_sources(self):
            raise RuntimeError("db gone")

    AppAttentionStep(BrokenStore(), ExplodingIngest(), fetch=RecordingFetch()).run(_at(0))


def test_프로젝트_서비스_중_하나라도_down이면_프로젝트_down으로_본다():
    def service(service_id, project_id="elum"):
        return ServiceSpec(service_id, service_id, project_id)

    registry = Registry(projects=(ELUM,), services=(service("elum-api"), service("elum-admin"),
                                                    service("other-api", "other")))
    down = replace(INITIAL_STATE, status="down")
    assert is_any_project_service_down(registry, {"elum-admin": down}, "elum") is True
    assert is_any_project_service_down(registry, {"other-api": down}, "elum") is False
    assert is_any_project_service_down(registry, {}, "elum") is False
    assert is_any_project_service_down(None, {"elum-api": down}, "elum") is False


def test_폴러_틱이_앱_확인할_일_단계를_틱마다_호출한다(registry_path, store, dispatcher):
    clock, calls = FakeClock(), []

    class FakeStep:
        def run(self, now):
            calls.append(now)

    poller = ControlTowerPoller(str(registry_path), store, dispatcher, None,
                                check_runner=FakeCheckRunner(clock), now=clock, environ={},
                                app_attention_step=FakeStep())
    run_ticks(poller, clock, 2)
    assert len(calls) == 2
