"""관제소 저장소: 상태 왕복, 장애 구간, 일별 집계(KST), 이벤트 중복 억제, 바인딩, 점검 창, 보관 정리"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from service.control_tower.check_runner import CheckResult
from service.control_tower.state_machine import INITIAL_STATE, Observation, ServiceState
from service.control_tower.store import ControlTowerStore

SERVICE_ID = "elum-api"
BASE_TIME = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)  # KST 09:00


def _result(is_ok: bool = True, is_slow: bool = False) -> CheckResult:
    return CheckResult(is_ok, is_slow, 200 if is_ok else None, 120, None if is_ok else "timeout", BASE_TIME)


OK = Observation(_result(), None, False)
FAIL = Observation(_result(False), None, False)
NO_DATA = Observation(None, _result(False), False)
EXTERNAL_FAIL = Observation(_result(), _result(False), True)


@pytest.fixture
def store(tmp_path):
    control_tower_store = ControlTowerStore(str(tmp_path / "nested" / "control_tower.db"))
    control_tower_store.initialize()
    yield control_tower_store
    control_tower_store.close()


def test_상태_저장_후_새_저장소에서_재로드하면_값이_그대로다(tmp_path):
    path = str(tmp_path / "control_tower.db")
    first_store = ControlTowerStore(path)
    first_store.initialize()
    saved_state = ServiceState("down", 3, 0, "service_down", BASE_TIME, BASE_TIME + timedelta(hours=1), True)
    first_store.save_state(SERVICE_ID, saved_state)
    first_store.save_state("unknown-one", INITIAL_STATE)
    first_store.close()

    restarted_store = ControlTowerStore(path)
    restarted_store.initialize()
    loaded_states = restarted_store.load_states()
    restarted_store.close()

    assert loaded_states[SERVICE_ID] == saved_state
    assert loaded_states["unknown-one"] == INITIAL_STATE


def test_상태_저장은_같은_서비스를_덮어쓴다(store):
    store.save_state(SERVICE_ID, ServiceState("down", 3, 0, "service_down", BASE_TIME, None, True))
    store.save_state(SERVICE_ID, ServiceState("up", 0, 2, None, BASE_TIME, None, False))

    assert store.load_states()[SERVICE_ID].status == "up"


def test_장애를_열고_닫으면_구간이_기록된다(store):
    incident_id = store.open_incident(SERVICE_ID, "service_down", BASE_TIME)
    closed_id = store.close_incident(SERVICE_ID, BASE_TIME + timedelta(minutes=30))

    assert closed_id == incident_id
    recent = store.recent_incidents(10, BASE_TIME - timedelta(days=1))
    assert recent == [{"id": incident_id, "service_id": SERVICE_ID, "cause": "service_down",
                       "started_at": BASE_TIME, "ended_at": BASE_TIME + timedelta(minutes=30),
                       "is_within_maintenance": False}]


def test_이미_열린_장애가_있으면_중복으로_열지_않는다(store):
    first_id = store.open_incident(SERVICE_ID, "service_down", BASE_TIME)
    second_id = store.open_incident(SERVICE_ID, "external_path", BASE_TIME + timedelta(minutes=1))

    assert second_id == first_id
    assert len(store.recent_incidents(10, BASE_TIME - timedelta(days=1))) == 1


def test_장애의_점검_창_안_여부는_열기와_닫기_모두_점검_중일_때만_참이다(store):
    store.open_incident("inside", "service_down", BASE_TIME, is_in_maintenance=True)
    store.close_incident("inside", BASE_TIME + timedelta(minutes=5), is_in_maintenance=True)
    store.open_incident("ended-after", "service_down", BASE_TIME, is_in_maintenance=True)
    store.close_incident("ended-after", BASE_TIME + timedelta(minutes=5), is_in_maintenance=False)
    store.open_incident("started-before", "service_down", BASE_TIME, is_in_maintenance=False)
    store.close_incident("started-before", BASE_TIME + timedelta(minutes=5), is_in_maintenance=True)

    flags = {row["service_id"]: row["is_within_maintenance"]
             for row in store.recent_incidents(10, BASE_TIME - timedelta(days=1))}

    assert flags == {"inside": True, "ended-after": False, "started-before": False}


def test_기존_DB의_장애_테이블에_점검_창_열을_추가한다(tmp_path):
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE incident (id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, "
                           "cause TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT)")
        connection.execute("INSERT INTO incident (service_id, cause, started_at) VALUES ('old', 'service_down', ?)",
                           (BASE_TIME.isoformat(),))
    connection.close()
    old_store = ControlTowerStore(path)

    old_store.initialize()
    old_store.initialize()  # 반복 실행 안전

    rows = old_store.recent_incidents(10, BASE_TIME - timedelta(days=1))
    old_store.close()
    assert [(row["service_id"], row["is_within_maintenance"]) for row in rows] == [("old", False)]


def test_열린_장애가_없으면_닫기는_None이다(store):
    assert store.close_incident(SERVICE_ID, BASE_TIME) is None


def test_최근_장애는_최신순이고_since_이전_종료분은_제외하되_열린_장애는_포함한다(store):
    old_id = store.open_incident("old-service", "service_down", BASE_TIME - timedelta(days=10))
    store.close_incident("old-service", BASE_TIME - timedelta(days=9))
    open_old_id = store.open_incident("open-old", "service_down", BASE_TIME - timedelta(days=20))
    new_id = store.open_incident(SERVICE_ID, "service_down", BASE_TIME)

    recent = store.recent_incidents(10, BASE_TIME - timedelta(days=5))

    assert [row["id"] for row in recent] == [new_id, open_old_id]
    assert old_id not in [row["id"] for row in recent]
    assert recent[0]["ended_at"] is None
    assert len(store.recent_incidents(1, BASE_TIME - timedelta(days=5))) == 1


def test_일별_집계는_KST_자정을_기준으로_나뉜다(store):
    before_midnight = datetime(2026, 11, 5, 14, 59, tzinfo=timezone.utc)  # KST 11-05 23:59
    after_midnight = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)  # KST 11-06 00:00
    store.save_results(SERVICE_ID, OK, before_midnight)
    store.save_results(SERVICE_ID, FAIL, after_midnight)
    store.save_results(SERVICE_ID, OK, after_midnight + timedelta(minutes=1))

    assert store.uptime_by_day(SERVICE_ID, 7) == [("2026-11-05", 1, 1), ("2026-11-06", 2, 1)]


def test_외부_실패와_데이터_없음_틱의_집계_규칙(store):
    store.save_results(SERVICE_ID, EXTERNAL_FAIL, BASE_TIME)  # 알려진 외부 실패 = 실패 틱
    store.save_results(SERVICE_ID, NO_DATA, BASE_TIME + timedelta(minutes=1))  # 미확인 외부 = 데이터 없음, 미집계
    store.save_results(SERVICE_ID, OK, BASE_TIME + timedelta(minutes=2))

    assert store.uptime_by_day(SERVICE_ID, 7) == [("2026-11-06", 2, 1)]


def test_가동률_조회는_최근_N일만_오래된_순으로_준다(store):
    for day_offset in range(5):
        store.save_results(SERVICE_ID, OK, BASE_TIME - timedelta(days=day_offset))

    days = [row[0] for row in store.uptime_by_day(SERVICE_ID, 3)]

    assert days == ["2026-11-04", "2026-11-05", "2026-11-06"]


def test_이벤트는_10분_안_같은_키면_False다(store):
    assert store.record_event("elum", "error", "err-1", BASE_TIME) is True
    assert store.record_event("elum", "error", "err-1", BASE_TIME + timedelta(minutes=9)) is False
    assert store.record_event("elum", "error", "err-1", BASE_TIME + timedelta(minutes=11)) is True
    assert store.record_event("romrom", "error", "err-1", BASE_TIME) is True  # 프로젝트가 다르면 별개


def test_dedupe_키가_비면_항상_True다(store):
    assert store.record_event("elum", "info", "", BASE_TIME) is True
    assert store.record_event("elum", "info", "", BASE_TIME) is True
    assert store.record_event("elum", "info", None, BASE_TIME) is True


def test_바인딩은_덮어쓰고_없으면_None이다(store):
    assert store.get_binding("elum", "status") is None
    store.set_binding("elum", "status", "111")
    store.set_binding("elum", "status", "222")
    store.set_binding("global", "alert", "333")

    assert store.get_binding("elum", "status") == "222"
    assert store.get_binding("global", "alert") == "333"


def test_전체_바인딩은_scope_kind_키로_모두_돌려준다(store):
    assert store.all_bindings() == {}
    store.set_binding("elum", "role:member", "111")
    store.set_binding("global", "notice", "222")

    assert store.all_bindings() == {("elum", "role:member"): "111", ("global", "notice"): "222"}


def test_메타는_저장하고_덮어쓴다(store):
    assert store.get_meta("last_digest_day") is None
    store.set_meta("last_digest_day", "2026-11-05")
    store.set_meta("last_digest_day", "2026-11-06")

    assert store.get_meta("last_digest_day") == "2026-11-06"


def test_점검_창은_아직_끝나지_않은_것만_돌려주고_해제할_수_있다(store):
    store.set_maintenance("elum-api", BASE_TIME + timedelta(hours=1), "업데이트")
    store.set_maintenance("romrom-api", BASE_TIME - timedelta(minutes=1), "지난 점검")
    store.set_maintenance("nas", BASE_TIME + timedelta(hours=2), "")

    active = store.active_maintenance(BASE_TIME)
    assert set(active) == {"elum-api", "nas"}
    assert active["elum-api"].until == BASE_TIME + timedelta(hours=1)
    assert active["elum-api"].reason == "업데이트"

    store.clear_maintenance("elum-api")
    assert set(store.active_maintenance(BASE_TIME)) == {"nas"}


def test_점검_창은_같은_서비스를_덮어쓴다(store):
    store.set_maintenance("elum-api", BASE_TIME + timedelta(hours=1), "처음")
    store.set_maintenance("elum-api", BASE_TIME + timedelta(hours=3), "연장")

    assert store.active_maintenance(BASE_TIME)["elum-api"].reason == "연장"


def test_보관_정리는_경계_안쪽은_남기고_바깥은_지운다(store):
    now = datetime(2026, 12, 31, 0, 0, tzinfo=timezone.utc)
    # check_result 7일
    store.save_results(SERVICE_ID, OK, now - timedelta(days=7, minutes=1))
    store.save_results(SERVICE_ID, OK, now - timedelta(days=6, hours=23))
    # event_log 30일 (dedupe 없음이라 모두 저장)
    store.record_event("elum", "info", "", now - timedelta(days=30, minutes=1))
    store.record_event("elum", "info", "", now - timedelta(days=29))
    # closed incident 400일, 열린 장애는 보존
    store.open_incident("gone", "service_down", now - timedelta(days=402))
    store.close_incident("gone", now - timedelta(days=401))
    store.open_incident("kept-open", "service_down", now - timedelta(days=402))
    store.open_incident("kept-closed", "service_down", now - timedelta(days=399))
    store.close_incident("kept-closed", now - timedelta(days=398))

    store.purge(now)

    assert _count(store, "check_result") == 1
    assert _count(store, "event_log") == 1
    assert sorted(row["service_id"] for row in store.recent_incidents(10, now - timedelta(days=1000))) \
        == ["kept-closed", "kept-open"]
    assert store.uptime_by_day(SERVICE_ID, 400) == [("2026-12-24", 2, 2)]  # 400일 이내 집계는 유지


def test_일별_집계는_400일_넘은_날짜만_지운다(store):
    now = datetime(2026, 12, 31, 0, 0, tzinfo=timezone.utc)  # KST 12-31 09:00
    store.save_results(SERVICE_ID, OK, now - timedelta(days=401))
    store.save_results(SERVICE_ID, OK, now - timedelta(days=399))

    store.purge(now)

    assert len(store.uptime_by_day(SERVICE_ID, 1000)) == 1


def test_점검_결과_행에_내부_외부_열과_외부_수신_여부가_저장된다(store):
    store.save_results(SERVICE_ID, EXTERNAL_FAIL, BASE_TIME)

    row = store._connection().execute("SELECT * FROM check_result").fetchone()

    assert row["service_id"] == SERVICE_ID
    assert row["is_external_known"] == 1
    assert (row["internal_is_ok"], row["internal_is_slow"], row["internal_status_code"],
            row["internal_latency_milliseconds"], row["internal_error"]) == (1, 0, 200, 120, None)
    assert (row["external_is_ok"], row["external_is_slow"], row["external_status_code"],
            row["external_latency_milliseconds"], row["external_error"]) == (0, 0, None, 120, "timeout")


def test_외부_미수신_점검은_외부_열이_비고_수신_여부가_0이다(store):
    store.save_results(SERVICE_ID, NO_DATA, BASE_TIME)  # 데이터 없음 > 저장 안 함
    store.save_results(SERVICE_ID, Observation(_result(), _result(False), False), BASE_TIME)

    row = store._connection().execute("SELECT * FROM check_result").fetchone()

    assert row["is_external_known"] == 0
    assert row["external_is_ok"] is None and row["external_error"] is None


def test_같은_시각_재저장은_일별_집계를_중복_증가시키지_않는다(store):
    store.save_results(SERVICE_ID, OK, BASE_TIME)
    store.save_results(SERVICE_ID, FAIL, BASE_TIME)

    assert store.uptime_by_day(SERVICE_ID, 7) == [("2026-11-06", 1, 1)]
    assert _count(store, "check_result") == 1


def _count(store: ControlTowerStore, table: str) -> int:
    return store._connection().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
