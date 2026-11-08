"""앱 확인할 일 알림 규칙: new 증가분·쿨다운, threshold 왕복, state, level, 억제, 메시지 묶음, 연동 끊김·복구"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from service.control_tower.alert_planner import GLOBAL_SCOPE, INFRASTRUCTURE_KIND
from service.control_tower.app_attention_messages import build_item_notifications, build_source_health_notification
from service.control_tower.app_attention_models import AttentionItem
from service.control_tower.app_attention_rules import (
    DEFAULT_CHANNEL_KIND, AlertLine, evaluate_item_alerts, evaluate_source_health, resolve_effective_item,
)
from service.control_tower.app_attention_store import (
    AttentionItemAlertState, AttentionItemOverride, AttentionSource, StoredAttentionItem, new_attention_source_state,
)
from service.control_tower.discord_messages import DESCRIPTION_MAX_LENGTH

PROJECT_ID = "elum"
SOURCE_ID = "api"
BASE_TIME = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _count_item(count: int, total: int | None = None, level: str = "warning", key: str = "feedback.new",
                detail: str | None = None) -> AttentionItem:
    return AttentionItem(key=key, label="의견", kind="count", level=level, count=count, total=total,
                         admin_url="https://elum.example/admin/feedback", detail=detail)


def _gauge_item(value: float, limit: float | None = 80, level: str = "warning") -> AttentionItem:
    return AttentionItem(key="disk.usage", label="디스크", kind="gauge", level=level, value=value, limit=limit,
                         unit="%")


def _state_item(state: str, level: str = "critical") -> AttentionItem:
    return AttentionItem(key="batch.status", label="배치", kind="state", level=level, state=state)


def _stored(item: AttentionItem) -> StoredAttentionItem:
    return StoredAttentionItem(
        PROJECT_ID, SOURCE_ID, item.key, item.kind, item.label, item.level, item.group, item.description,
        item.admin_url, item.latest_at, item.detail, item.count, item.total, item.value, item.limit, item.unit,
        item.state, None, BASE_TIME, BASE_TIME, None)


class _Sequence:
    """수집 결과를 차례로 평가하며 이전 항목·알림 기준을 넘겨 주는 도우미 (호출부 역할)"""

    def __init__(self, first_item: AttentionItem, override: AttentionItemOverride | None = None):
        self.override = override
        self.previous_items: dict[str, StoredAttentionItem] = {}
        self.alert_states: dict[str, AttentionItemAlertState] = {}
        self.evaluate(first_item, BASE_TIME, is_baseline=True)

    def evaluate(self, item: AttentionItem, now: datetime, is_baseline: bool = False,
                 is_production: bool = True) -> list[AlertLine]:
        effective = resolve_effective_item(item, self.override)
        lines, next_states = evaluate_item_alerts([effective], self.previous_items, self.alert_states, is_baseline,
                                                  is_production, now)
        self.alert_states.update(next_states)
        self.previous_items[item.key] = _stored(item)
        return lines


def _line(level: str = "warning", channel_kind: str = DEFAULT_CHANNEL_KIND, key: str = "feedback.new",
          admin_url: str | None = "https://elum.example/admin/feedback", text: str = "+1, 지금 1건") -> AlertLine:
    return AlertLine(key=key, label="의견", level=level, admin_url=admin_url, text=text, channel_kind=channel_kind,
                     is_recovery=False)


def _source(stale_after_seconds: int = 300) -> AttentionSource:
    return AttentionSource(PROJECT_ID, SOURCE_ID, "https://elum.example/attention", True, "pull", 60, 5,
                           stale_after_seconds, BASE_TIME, BASE_TIME)


def test_count가_그대로여도_total이_늘면_new_알림이_나간다():
    sequence = _Sequence(_count_item(count=3, total=10))
    lines = sequence.evaluate(_count_item(count=3, total=11), BASE_TIME + timedelta(minutes=1))
    assert [line.text for line in lines] == ["+1, 지금 3건"]
    assert lines[0].label == "의견" and lines[0].channel_kind == DEFAULT_CHANNEL_KIND


def test_total이_없으면_count_증가분으로_알리고_줄면_알리지_않는다():
    sequence = _Sequence(_count_item(count=3))
    assert sequence.evaluate(_count_item(count=1), BASE_TIME + timedelta(minutes=1)) == []
    lines = sequence.evaluate(_count_item(count=6, detail="최근: 앱이 느려요"), BASE_TIME + timedelta(minutes=2))
    assert [line.text for line in lines] == ["+5, 지금 6건 · 최근: 앱이 느려요"]


def test_new_쿨다운_안의_증가분은_다음_알림에_합산된다():
    sequence = _Sequence(_count_item(count=0, total=0))
    sequence.alert_states["feedback.new"] = AttentionItemAlertState(
        PROJECT_ID, SOURCE_ID, "feedback.new", last_alerted_at=BASE_TIME, last_alerted_total=0, last_alerted_count=0,
        last_alerted_level="warning")
    assert sequence.evaluate(_count_item(count=3, total=3), BASE_TIME + timedelta(minutes=1)) == []
    assert sequence.evaluate(_count_item(count=5, total=5), BASE_TIME + timedelta(minutes=5)) == []
    assert sequence.alert_states["feedback.new"].pending_new_count == 5
    lines = sequence.evaluate(_count_item(count=6, total=6), BASE_TIME + timedelta(minutes=11))
    assert [line.text for line in lines] == ["+6, 지금 6건"]
    assert sequence.alert_states["feedback.new"].pending_new_count == 0
    assert sequence.alert_states["feedback.new"].last_alerted_at == BASE_TIME + timedelta(minutes=11)


def test_threshold는_넘을_때_1번_내려올_때_해소_1번만_알린다():
    sequence = _Sequence(_gauge_item(value=50))
    exceeded_lines = sequence.evaluate(_gauge_item(value=85), BASE_TIME + timedelta(minutes=1))
    assert [(line.text, line.is_recovery) for line in exceeded_lines] == [("85%, 기준 80% 넘음", False)]
    assert sequence.evaluate(_gauge_item(value=90), BASE_TIME + timedelta(minutes=2)) == []
    recovered_lines = sequence.evaluate(_gauge_item(value=70, level="ok"), BASE_TIME + timedelta(minutes=3))
    assert [(line.text, line.is_recovery, line.level) for line in recovered_lines] == [
        ("70%, 기준 80% 아래로 내려옴", True, "warning")]
    assert sequence.evaluate(_gauge_item(value=60), BASE_TIME + timedelta(minutes=4)) == []


def test_threshold_덮어쓰기가_항목_limit보다_우선하고_기준이_없으면_알리지_않는다():
    override = AttentionItemOverride(PROJECT_ID, SOURCE_ID, "disk.usage", threshold=95)
    sequence = _Sequence(_gauge_item(value=50), override)
    assert sequence.evaluate(_gauge_item(value=90), BASE_TIME + timedelta(minutes=1)) == []
    assert len(sequence.evaluate(_gauge_item(value=96), BASE_TIME + timedelta(minutes=2))) == 1
    no_limit_sequence = _Sequence(_gauge_item(value=50, limit=None))
    assert no_limit_sequence.evaluate(_gauge_item(value=999, limit=None), BASE_TIME + timedelta(minutes=1)) == []


def test_state는_비정상_진입_비정상끼리_변화_정상_복귀를_각각_1줄로_알린다():
    sequence = _Sequence(_state_item("ok", level="ok"))
    degraded = sequence.evaluate(_state_item("degraded", level="warning"), BASE_TIME + timedelta(minutes=1))
    assert [(line.text, line.is_recovery) for line in degraded] == [("상태 ok > degraded", False)]
    assert sequence.evaluate(_state_item("degraded", level="warning"), BASE_TIME + timedelta(minutes=2)) == []
    down = sequence.evaluate(_state_item("down", level="critical"), BASE_TIME + timedelta(minutes=3))
    assert [(line.text, line.level) for line in down] == [("상태 degraded > down", "critical")]
    recovered = sequence.evaluate(_state_item("ok", level="ok"), BASE_TIME + timedelta(minutes=4))
    assert [(line.text, line.is_recovery, line.level) for line in recovered] == [("상태 down > ok", True, "critical")]


def test_level_규칙은_warning_이상으로_오를_때만_알린다():
    def unknown_item(level: str) -> AttentionItem:
        return AttentionItem(key="release.note", label="출시", kind="checklist", level=level)

    sequence = _Sequence(unknown_item("ok"))
    assert resolve_effective_item(unknown_item("ok"), None).rule == "level"
    assert sequence.evaluate(unknown_item("info"), BASE_TIME + timedelta(minutes=1)) == []
    assert [line.text for line in sequence.evaluate(unknown_item("warning"), BASE_TIME + timedelta(minutes=2))] == [
        "수준 info > warning"]
    assert sequence.evaluate(unknown_item("info"), BASE_TIME + timedelta(minutes=3)) == []
    assert len(sequence.evaluate(unknown_item("critical"), BASE_TIME + timedelta(minutes=4))) == 1


def test_기준선이나_비production이면_알리지_않고_기준만_현재값으로_맞춘다():
    sequence = _Sequence(_count_item(count=3, total=10))
    assert sequence.evaluate(_count_item(count=9, total=20), BASE_TIME + timedelta(minutes=1), is_baseline=True) == []
    assert sequence.alert_states["feedback.new"].last_alerted_total == 20
    assert sequence.evaluate(_count_item(count=9, total=25), BASE_TIME + timedelta(minutes=2),
                             is_production=False) == []
    assert sequence.alert_states["feedback.new"].last_alerted_total == 25
    lines = sequence.evaluate(_count_item(count=9, total=26), BASE_TIME + timedelta(minutes=3))
    assert [line.text for line in lines] == ["+1, 지금 9건"]


def test_처음_보는_key는_기준만_저장하고_알리지_않는다():
    lines, next_states = evaluate_item_alerts([resolve_effective_item(_count_item(count=50, total=50), None)], {}, {},
                                              False, True, BASE_TIME)
    assert lines == []
    assert next_states["feedback.new"].last_alerted_total == 50


def test_숨김_off_유효수준_ok는_알리지_않지만_기준은_갱신한다():
    overrides = [
        AttentionItemOverride(PROJECT_ID, SOURCE_ID, "feedback.new", is_hidden=True),
        AttentionItemOverride(PROJECT_ID, SOURCE_ID, "feedback.new", alert_rule="off"),
        AttentionItemOverride(PROJECT_ID, SOURCE_ID, "feedback.new", level_policy="ok"),
    ]
    for override in overrides:
        sequence = _Sequence(_count_item(count=1, total=1), override)
        assert sequence.evaluate(_count_item(count=4, total=4), BASE_TIME + timedelta(minutes=1)) == []
        assert sequence.alert_states["feedback.new"].last_alerted_total == 4
    app_ok_sequence = _Sequence(_count_item(count=1, total=1, level="ok"))
    assert app_ok_sequence.evaluate(_count_item(count=4, total=4, level="ok"), BASE_TIME + timedelta(minutes=1)) == []


def test_유효_설정은_덮어쓰기가_앱_값과_기본_규칙보다_우선한다():
    override = AttentionItemOverride(PROJECT_ID, SOURCE_ID, "feedback.new", label="고객 의견", level_policy="critical",
                                     alert_rule="level", channel_kind="report")
    effective = resolve_effective_item(_count_item(count=1), override)
    assert (effective.label, effective.level, effective.rule, effective.channel_kind, effective.is_hidden) == (
        "고객 의견", "critical", "level", "report", False)
    default = resolve_effective_item(_gauge_item(value=1), None)
    assert (default.rule, default.threshold, default.channel_kind) == ("threshold", 80, DEFAULT_CHANNEL_KIND)


def test_알림은_채널별_1건으로_묶고_critical이_있으면_전역_긴급을_추가한다():
    lines = [_line("warning"), _line("critical", key="batch.status", admin_url=None, text="상태 ok > down"),
             _line("info", channel_kind="report", key="report.weekly")]
    notifications = build_item_notifications(PROJECT_ID, "elum", SOURCE_ID, lines, "tick1")
    by_target = {(notification.scope, notification.kind): notification for notification in notifications}
    assert set(by_target) == {(PROJECT_ID, DEFAULT_CHANNEL_KIND), (PROJECT_ID, "report"),
                              (GLOBAL_SCOPE, INFRASTRUCTURE_KIND)}
    attention = by_target[(PROJECT_ID, DEFAULT_CHANNEL_KIND)]
    assert attention.title == "elum 확인할 일"
    assert attention.severity == "critical"
    assert attention.body == ("• 의견 상태 ok > down\n"
                              "• [의견](https://elum.example/admin/feedback) +1, 지금 1건")
    assert attention.link_url == "https://elum.example/admin/feedback"
    assert attention.dedupe_key.startswith(f"attention:{PROJECT_ID}:{SOURCE_ID}:tick1")
    assert by_target[(PROJECT_ID, "report")].severity == "info"
    assert by_target[(GLOBAL_SCOPE, INFRASTRUCTURE_KIND)].body == "• 의견 상태 ok > down"
    assert len({notification.dedupe_key for notification in notifications}) == 3


def test_critical_없으면_전역_긴급이_없고_warning이_최고_심각도다():
    notifications = build_item_notifications(PROJECT_ID, "elum", SOURCE_ID, [_line("info"), _line("warning")], "t")
    assert [(notification.scope, notification.severity) for notification in notifications] == [(PROJECT_ID, "warning")]


def test_본문이_한도를_넘으면_높은_수준_줄부터_남기고_외_N건을_붙인다():
    long_text = "가" * 300
    lines = [_line("info", key=f"item.info{index}", text=long_text) for index in range(30)]
    lines.append(_line("critical", key="item.critical", text=long_text))
    notification = build_item_notifications(PROJECT_ID, "elum", SOURCE_ID, lines, "t")[0]
    assert len(notification.body) <= DESCRIPTION_MAX_LENGTH
    body_lines = notification.body.split("\n")
    assert body_lines[-1] == f"외 {31 - (len(body_lines) - 1)}건"
    assert notification.severity == "critical"
    assert notification.body.startswith("• [의견]")


def test_링크_이름의_대괄호와_주소의_괄호는_마크다운이_깨지지_않게_바꾼다():
    line = AlertLine(key="a.b", label="[중요] 의견", level="info", admin_url="https://x.example/a_(b)", text="+1",
                     channel_kind=DEFAULT_CHANNEL_KIND, is_recovery=False)
    notification = build_item_notifications(PROJECT_ID, "elum", SOURCE_ID, [line], "t")[0]
    assert notification.body == "• [\\[중요\\] 의견](https://x.example/a_%28b%29) +1"


def test_연동_끊김은_한_번만_판정하고_복구도_한_번만_판정한다():
    source = _source(stale_after_seconds=300)
    state = new_attention_source_state(PROJECT_ID, SOURCE_ID)
    # 성공 이력 없음: 등록 시각 기준
    assert evaluate_source_health(source, state, False, BASE_TIME + timedelta(seconds=300)) is None
    assert evaluate_source_health(source, state, False, BASE_TIME + timedelta(seconds=301)) == "disconnected"
    # 마지막 성공 기준
    succeeded = replace(state, last_success_at=BASE_TIME + timedelta(minutes=10), last_result="timeout")
    assert evaluate_source_health(source, succeeded, False, BASE_TIME + timedelta(minutes=14)) is None
    assert evaluate_source_health(source, succeeded, False, BASE_TIME + timedelta(minutes=16)) == "disconnected"
    # 끊김 알림 후에는 다시 판정하지 않음
    alerted = replace(succeeded, failure_alerted_at=BASE_TIME + timedelta(minutes=16))
    assert evaluate_source_health(source, alerted, False, BASE_TIME + timedelta(hours=5)) is None
    # 성공 직후 복구 1번 (304 포함), 알림 기록 지운 뒤에는 없음
    for success_result in ("ok", "not_modified"):
        recovered = replace(alerted, last_result=success_result, last_success_at=BASE_TIME + timedelta(hours=5))
        assert evaluate_source_health(source, recovered, False, BASE_TIME + timedelta(hours=5)) == "recovered"
    cleared = replace(recovered, failure_alerted_at=None)
    assert evaluate_source_health(source, cleared, False, BASE_TIME + timedelta(hours=5)) is None


def test_프로젝트가_down이거나_소스가_꺼져_있으면_연동_끊김을_생략한다():
    state = new_attention_source_state(PROJECT_ID, SOURCE_ID)
    later = BASE_TIME + timedelta(hours=1)
    assert evaluate_source_health(_source(), state, True, later) is None
    disabled = AttentionSource(PROJECT_ID, SOURCE_ID, "https://elum.example/attention", False, "pull", 60, 5, 300,
                               BASE_TIME, BASE_TIME)
    assert evaluate_source_health(disabled, state, False, later) is None
    assert evaluate_source_health(_source(), None, False, later) == "disconnected"


def test_연동_알림은_프로젝트_error_채널로_끊김은_사유를_복구는_recovered로_보낸다():
    disconnected = build_source_health_notification(PROJECT_ID, "elum", SOURCE_ID, "disconnected", "unauthorized")
    assert (disconnected.scope, disconnected.kind, disconnected.severity) == (PROJECT_ID, "error", "warning")
    assert disconnected.title == "elum 확인할 일 연동 끊김"
    assert "사유: unauthorized" in disconnected.body
    recovered = build_source_health_notification(PROJECT_ID, "elum", SOURCE_ID, "recovered", None)
    assert (recovered.title, recovered.severity) == ("elum 확인할 일 연동 복구", "recovered")
    assert disconnected.dedupe_key != recovered.dedupe_key
