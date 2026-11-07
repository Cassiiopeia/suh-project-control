"""관제소 일일 요약: 100% 미만 서비스 나열, 활성 서비스만, 하루 경계(KST), 장애 건수·다운 시간, 데이터 없음"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from service.control_tower.check_runner import CheckResult
from service.control_tower.digest import build_daily_digest
from service.control_tower.registry import CheckSpec, ProjectSpec, Registry, ServiceSpec
from service.control_tower.state_machine import Observation
from service.control_tower.store import ControlTowerStore

KST = timezone(timedelta(hours=9))
DAY = date(2026, 11, 5)
DAY_START = datetime(2026, 11, 5, 0, 0, tzinfo=KST)
TCP_CHECK = CheckSpec("tcp", "nas.local:5001")

REGISTRY = Registry(
    projects=(ProjectSpec("elum", "이룸"),),
    services=(
        ServiceSpec("elum-api", "이룸 API", "elum", internal=TCP_CHECK),
        ServiceSpec("elum-web", "이룸 웹", "elum", internal=TCP_CHECK),
        ServiceSpec("elum-old", "이룸 구버전", "elum", status="paused", internal=TCP_CHECK),
    ),
    infrastructure=(ServiceSpec("nas", "시놀로지 NAS", None, internal=TCP_CHECK),),
)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def _record_ticks(store: ControlTowerStore, service_id: str, results: list[bool], start: datetime) -> None:
    """1분 간격 점검 결과 기록 (일별 집계 반영)"""
    for index, is_ok in enumerate(results):
        moment = start + timedelta(minutes=index)
        check = CheckResult(is_ok, False, None, 5, None if is_ok else "timeout", moment)
        store.save_results(service_id, Observation(check, None, False), moment)


def test_요약은_전역_digest_알림이고_제목과_중복키에_날짜가_들어간다(store):
    _record_ticks(store, "elum-api", [True], DAY_START)

    notification = build_daily_digest(REGISTRY, store, DAY)

    assert (notification.scope, notification.kind, notification.severity) == ("global", "digest", "info")
    assert notification.title == "[일일 요약] 2026-11-05"
    assert notification.dedupe_key == "digest:2026-11-05"


def test_가동률_100퍼센트_미만인_활성_서비스만_나열한다(store):
    _record_ticks(store, "elum-api", [True, False, True], DAY_START + timedelta(hours=1))
    _record_ticks(store, "elum-web", [True, True], DAY_START + timedelta(hours=1))
    _record_ticks(store, "elum-old", [False, False], DAY_START + timedelta(hours=1))
    _record_ticks(store, "nas", [False] + [True] * 199, DAY_START + timedelta(hours=2))

    body = build_daily_digest(REGISTRY, store, DAY).body

    assert "이룸 API: 66.67%" in body
    assert "시놀로지 NAS: 99.50%" in body
    assert "이룸 웹" not in body
    assert "이룸 구버전" not in body


def test_다른_날의_집계는_쓰지_않는다(store):
    _record_ticks(store, "elum-api", [False], DAY_START - timedelta(minutes=1))  # 전날 23:59 KST
    _record_ticks(store, "elum-api", [False], DAY_START + timedelta(days=1))  # 다음 날 00:00 KST
    _record_ticks(store, "elum-api", [True], DAY_START)

    assert "모든 서비스 정상 (100%)" in build_daily_digest(REGISTRY, store, DAY).body


def test_전부_100퍼센트면_모든_서비스_정상_문구를_쓴다(store):
    _record_ticks(store, "elum-api", [True, True], DAY_START)
    _record_ticks(store, "nas", [True], DAY_START)

    body = build_daily_digest(REGISTRY, store, DAY).body

    assert "모든 서비스 정상 (100%)" in body
    assert "장애 없음" in body


def test_집계가_하나도_없으면_데이터_없음_문구를_쓴다(store):
    assert "집계 데이터 없음" in build_daily_digest(REGISTRY, store, DAY).body


def test_그날과_겹친_장애_건수와_그날_안의_다운_시간_합계를_적는다(store):
    _record_ticks(store, "elum-api", [False], DAY_START)
    # 전날 23:30 시작 > 00:30 종료: 그날 안 30분
    store.open_incident("elum-api", "service_down", DAY_START - timedelta(minutes=30))
    store.close_incident("elum-api", DAY_START + timedelta(minutes=30))
    # 10:00 시작 > 11:00 종료: 1시간
    store.open_incident("nas", "service_down", DAY_START + timedelta(hours=10))
    store.close_incident("nas", DAY_START + timedelta(hours=11))
    # 23:00 시작 진행 중: 그날 안 1시간
    store.open_incident("elum-web", "service_down", DAY_START + timedelta(hours=23))
    # 비활성 서비스·다른 날 장애는 제외
    store.open_incident("elum-old", "service_down", DAY_START + timedelta(hours=1))
    store.open_incident("nas", "service_down", DAY_START + timedelta(days=1, hours=1))

    body = build_daily_digest(REGISTRY, store, DAY).body

    assert "장애 3건, 총 다운 시간 2시간 30분" in body
