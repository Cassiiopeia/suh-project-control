"""알림 전송 결과"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NotifyResult:
    """전송 결과: 접수 여부, HTTP 상태, 실패 코드, 중복 억제 여부 (예외 대신 결과로 돌려줌)"""

    # 서버가 접수(202)했는지
    is_accepted: bool
    # HTTP 상태 코드 (네트워크 오류·시간 초과·init 전은 None)
    status_code: Optional[int] = None
    # 실패 코드: 서버 error 값 | http_<상태> | timeout | connection_error | not_initialized
    error_code: Optional[str] = None
    # dedupe_key 중복으로 알림 없이 접수만 됐는지
    is_deduplicated: bool = False
