"""앱 확인할 일(attention v1) 모델: 항목·스냅샷 데이터 클래스와 규격 상수
규격 원본은 docs/control-tower/attention/attention-v1.schema.json (상수 값을 함께 바꿔야 함)"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# 항목 종류 3종 (그 외 kind는 label·detail·level만 표시)
ITEM_KINDS = ("count", "gauge", "state")
# 심각도 (낮음 > 높음)
ITEM_LEVELS = ("ok", "info", "warning", "critical")
# state 항목의 상태값
ITEM_STATES = ("ok", "degraded", "down", "unknown")
# 앱 환경 (production 아니면 알림 안 함)
ENVIRONMENTS = ("production", "staging", "development")
DEFAULT_ENVIRONMENT = "production"

# 지원하는 규격 주 버전
SUPPORTED_MAJOR_VERSION = 1
SCHEMA_NAME = "attention"

# 개수·크기 상한
MAX_ITEM_COUNT = 100
MAX_BODY_BYTES = 65536
# 글자 수 상한
MAX_KEY_LENGTH = 64
MAX_LABEL_LENGTH = 40
MAX_GROUP_LENGTH = 20
MAX_DESCRIPTION_LENGTH = 200
MAX_DETAIL_LENGTH = 80
MAX_UNIT_LENGTH = 12
MAX_URL_LENGTH = 2048
SOURCE_ID_MAX_LENGTH = 20

# 소스 수집 설정 범위 (초)
TIMEOUT_SECONDS_DEFAULT = 5
TIMEOUT_SECONDS_MIN = 1
TIMEOUT_SECONDS_MAX = 10
INTERVAL_SECONDS_DEFAULT = 60
INTERVAL_SECONDS_MIN = 60
INTERVAL_SECONDS_MAX = 3600
# push 전용 소스가 변화 없이도 스냅샷을 보내야 하는 최소 주기 (끊김 판정 기준)
PUSH_ONLY_MIN_PERIOD_SECONDS = 300
# 끊김 판정 기본 배수 (interval x 5)
STALE_AFTER_INTERVAL_MULTIPLIER = 5

# 소스 id: 소문자로 시작, 소문자·숫자 (구분자 "__"와 충돌하지 않게 - _ 금지)
SOURCE_ID_PATTERN = r"^[a-z][a-z0-9]*$"
# 항목 key: 점으로 구분한 2~4마디 (예: feedback.new)
ITEM_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,3}$"
# kind: 모르는 kind도 허용
ITEM_KIND_PATTERN = r"^[a-z][a-z0-9_]*$"
# 버전 "주.부" (주 버전 1만 받음)
VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
# UTC ISO 8601: 2026-11-08T12:00:00Z, 소수초 최대 9자리, 오프셋 허용
TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,9})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$"
)


@dataclass(frozen=True)
class AttentionItem:
    """확인할 일 1건 (kind별로 쓰는 칸이 다르고 나머지는 None)"""
    key: str
    label: str
    kind: str
    level: str
    group: str | None = None
    description: str | None = None
    admin_url: str | None = None
    latest_at: datetime | None = None
    detail: str | None = None
    count: int | None = None
    total: int | None = None
    value: float | None = None
    limit: float | None = None
    unit: str | None = None
    state: str | None = None
    raw: dict | None = None  # 앱이 보낸 원본 항목


@dataclass(frozen=True)
class AttentionSnapshot:
    """한 소스의 현재 항목 전체 (스냅샷 교체 의미)"""
    major_version: int
    app: str
    app_version: str | None
    environment: str
    admin_base_url: str | None
    generated_at: datetime
    poll_after_seconds: int | None
    items: tuple[AttentionItem, ...]
