"""앱 확인할 일 유효 설정: 앱 항목 + 관제소 덮어쓰기 > 표시 이름·유효 수준·알림 규칙·기준값·채널 (순수 함수)
우선순위: 덮어쓰기 > kind별 기본값 (덮어쓰기 칸이 None이면 앱 값·기본 규칙)"""
from __future__ import annotations

from dataclasses import dataclass

from service.control_tower.app_attention_models import ITEM_LEVELS, AttentionItem
from service.control_tower.app_attention_store import AttentionItemOverride

# 알림 규칙 5종: new 증가분, threshold 기준 넘김·해소, state 상태 변화, level 수준 상승, off 알림 없음
ALERT_RULE_NEW = "new"
ALERT_RULE_THRESHOLD = "threshold"
ALERT_RULE_STATE = "state"
ALERT_RULE_LEVEL = "level"
ALERT_RULE_OFF = "off"
ALERT_RULES = (ALERT_RULE_NEW, ALERT_RULE_THRESHOLD, ALERT_RULE_STATE, ALERT_RULE_LEVEL, ALERT_RULE_OFF)
# 수준 정책: app 앱 값 사용(기본), 고정값 info/warning/critical, ok 알림 안 하는 정보성
LEVEL_POLICY_APP = "app"
LEVEL_POLICIES = (LEVEL_POLICY_APP, "info", "warning", "critical", "ok")
# kind별 기본 규칙 (그 외 kind는 level)
DEFAULT_RULE_BY_KIND = {"count": ALERT_RULE_NEW, "gauge": ALERT_RULE_THRESHOLD, "state": ALERT_RULE_STATE}
# 프로젝트 확인할 일 채널 종류 (#확인할일)
DEFAULT_CHANNEL_KIND = "attention"
LEVEL_OK = "ok"
LEVEL_CRITICAL = "critical"


@dataclass(frozen=True)
class EffectiveItem:
    """덮어쓰기를 반영한 항목 1건 (item은 앱이 보낸 원본 그대로)"""
    item: AttentionItem
    label: str
    level: str  # 유효 수준 (ok < info < warning < critical)
    rule: str  # ALERT_RULES 중 하나
    threshold: float | None  # threshold 규칙 기준 (덮어쓰기 > 항목 limit)
    channel_kind: str
    is_hidden: bool


def resolve_effective_item(item: AttentionItem, override: AttentionItemOverride | None) -> EffectiveItem:
    """앱 항목 + 덮어쓰기 > 유효 항목 (덮어쓰기 없음 = 앱 값·kind 기본 규칙·attention 채널)"""
    if override is None:
        override = AttentionItemOverride(project_id="", source_id="", key=item.key)
    return EffectiveItem(
        item=item,
        label=override.label or item.label,
        level=resolve_effective_level(item.level, override.level_policy),
        rule=override.alert_rule or DEFAULT_RULE_BY_KIND.get(item.kind, ALERT_RULE_LEVEL),
        threshold=override.threshold if override.threshold is not None else item.limit,
        channel_kind=override.channel_kind or DEFAULT_CHANNEL_KIND,
        is_hidden=bool(override.is_hidden),
    )


def resolve_effective_level(app_level: str, level_policy: str | None) -> str:
    """앱 수준 + 수준 정책 > 유효 수준 (정책 None·app = 앱 값, 그 외 = 고정값)"""
    if level_policy is None or level_policy == LEVEL_POLICY_APP:
        return app_level
    return level_policy


def level_rank(level: str | None) -> int:
    """수준 > 순위 (ok 0 ~ critical 3, 모르는 값·None은 ok와 같음)"""
    return ITEM_LEVELS.index(level) if level in ITEM_LEVELS else 0
