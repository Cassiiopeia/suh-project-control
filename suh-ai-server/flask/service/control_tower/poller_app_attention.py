"""앱 확인할 일 폴러 단계: 수집 대상 선별 > 병렬 수집(틱당 예산) > 처리 > 연동 끊김 판정
예산 초과 소스는 기다리지 않고 timeout 실패로 기록 (다음 틱이 밀리지 않게), 예외는 단계 밖으로 나가지 않음"""
from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from typing import Mapping

from service.control_tower.app_attention_fetch import (
    FETCH_RESULT_ERROR, FETCH_RESULT_TIMEOUT, FetchOutcome, fetch_attention,
)
from service.control_tower.app_attention_store import AttentionSource, AttentionSourceState
from service.control_tower.registry import Registry
from service.control_tower.state_machine import STATUS_DOWN, ServiceState

logger = logging.getLogger(__name__)

SOURCE_MODE_PUSH = "push"
# 수집 시점 여유 (주기 직전 틱에 수집)
DUE_MARGIN = timedelta(seconds=5)
MAX_FETCH_WORKERS = 8
TICK_BUDGET_SECONDS = 10
# 틱 예산 안에 끝나지 않은 수집의 실패 사유
ERROR_LABEL_TICK_BUDGET = "tick_budget"


def is_any_project_service_down(registry: Registry | None, states: Mapping[str, ServiceState],
                                project_id: str) -> bool:
    """프로젝트 서비스 중 하나라도 down이면 True (이 경우 앱 연동 끊김 알림은 서비스 장애에 묻음)"""
    if registry is None:
        return False
    return any(states.get(service.id) is not None and states[service.id].status == STATUS_DOWN
               for service in registry.services if service.project_id == project_id)


class AppAttentionStep:
    def __init__(self, store, ingest, fetch=fetch_attention, monotonic=time.monotonic,
                 max_workers: int = MAX_FETCH_WORKERS, tick_budget_seconds: float = TICK_BUDGET_SECONDS):
        self._store = store
        self._ingest = ingest
        self._fetch = fetch
        self._monotonic = monotonic
        self._max_workers = max_workers
        self._tick_budget_seconds = tick_budget_seconds

    def run(self, now: datetime) -> None:
        """틱 1회: 소스 조회 > 수집 대상 병렬 수집 > 처리 > 처리 안 된 활성 소스는 연동 판정만"""
        try:
            sources = [source for source in self._store.list_attention_sources() if source.is_enabled]
            states = self._store.list_attention_source_states()
            due_sources = [source for source in sources
                           if source.mode != SOURCE_MODE_PUSH
                           and _is_due(source, states.get((source.project_id, source.source_id)), now)]
            ingested_keys = self._collect_and_ingest(due_sources, states, now)
            for source in sources:
                if (source.project_id, source.source_id) not in ingested_keys:
                    self._check_source_health_safely(source, now)
        except Exception as error:
            logger.warning("[control-tower app-attention] step failed : %s", type(error).__name__)

    def _collect_and_ingest(self, due_sources: list[AttentionSource], states: dict, now: datetime) -> set:
        """병렬 수집 > 예산 안에 끝난 결과 처리 > 못 끝낸 소스는 timeout 실패 기록 > 처리한 소스 키 반환"""
        if not due_sources:
            return set()
        started_seconds = self._monotonic()
        executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="app-attention-fetch")
        try:
            futures = {executor.submit(self._fetch, source, _etag_of(states, source)): source
                       for source in due_sources}
            done, not_done = wait(futures, timeout=self._tick_budget_seconds)
        finally:
            # 못 끝낸 수집은 기다리지 않음 (소스 timeout 안에서 스스로 끝남, 결과는 버림)
            executor.shutdown(wait=False, cancel_futures=True)
        ingested_keys: set = set()
        for future in done:
            self._ingest_safely(futures[future], _outcome_of(future), now, ingested_keys)
        for future in not_done:
            if future.cancelled():  # 일꾼이 모자라 시작도 못 함 > 실패로 치지 않고 다음 틱에 다시
                continue
            source = futures[future]
            logger.warning("[control-tower app-attention] fetch over budget : %s.%s : %.1fs",
                           source.project_id, source.source_id, self._monotonic() - started_seconds)
            self._ingest_safely(source, FetchOutcome(FETCH_RESULT_TIMEOUT, None, None, ERROR_LABEL_TICK_BUDGET),
                                now, ingested_keys)
        return ingested_keys

    def _ingest_safely(self, source: AttentionSource, outcome: FetchOutcome, now: datetime,
                       ingested_keys: set) -> None:
        """소스 1건 처리 (예외는 로그만, 처리하면 연동 판정까지 끝난 것으로 표시)"""
        try:
            self._ingest.ingest(source, outcome, now)
            ingested_keys.add((source.project_id, source.source_id))
        except Exception as error:
            logger.warning("[control-tower app-attention] ingest failed : %s.%s : %s",
                           source.project_id, source.source_id, type(error).__name__)

    def _check_source_health_safely(self, source: AttentionSource, now: datetime) -> None:
        try:
            self._ingest.check_source_health(source, now)
        except Exception as error:
            logger.warning("[control-tower app-attention] health check failed : %s.%s : %s",
                           source.project_id, source.source_id, type(error).__name__)


def _is_due(source: AttentionSource, state: AttentionSourceState | None, now: datetime) -> bool:
    """수집 시점: 한 번도 안 했으면 즉시, 앱 요청 시각(next_due_at) 우선, 없으면 마지막 시도 + interval (여유 5초)"""
    if state is None or state.last_attempt_at is None:
        return True
    due_at = state.next_due_at or state.last_attempt_at + timedelta(seconds=source.interval_seconds)
    return due_at - DUE_MARGIN <= now


def _etag_of(states: dict, source: AttentionSource) -> str | None:
    state = states.get((source.project_id, source.source_id))
    return state.etag if state is not None else None


def _outcome_of(future: Future) -> FetchOutcome:
    """끝난 수집 결과 (수집 함수 예외는 error 결과로)"""
    try:
        return future.result()
    except Exception as error:
        logger.warning("[control-tower app-attention] fetch crashed : %s", type(error).__name__)
        return FetchOutcome(FETCH_RESULT_ERROR, None, None, "fetch_crashed")
