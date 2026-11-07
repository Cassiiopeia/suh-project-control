"""관제소 SQLite meta 키 단일 원본 (폴러·관리자 overview·디스코드 동기화 공용)"""
from __future__ import annotations

# 마지막 일일 요약·보관 정리 KST 일자 (YYYY-MM-DD)
META_KEY_LAST_DIGEST_DAY = "last_digest_day"
META_KEY_LAST_PURGE_DAY = "last_purge_day"
# 마지막 심박 성공 시각 (UTC ISO) / 직전 심박 성공 여부 ('1' 성공, '0' 실패·거절)
META_KEY_HEARTBEAT_LAST_OK_AT = "heartbeat_last_ok_at"
META_KEY_HEARTBEAT_IS_OK = "heartbeat_is_ok"
# 등록 파일 오류 요약 (정상이면 '')
META_KEY_REGISTRY_ERROR = "registry_error"
# 디스코드 온보딩 적용 해시 (없으면 미적용)
META_KEY_ONBOARDING_HASH = "discord_onboarding_hash"
# 공개 상태 페이지 제목 / 공지 문구(빈 값 = 공지 없음) / 공지 수준 (info | warning | critical)
META_KEY_STATUS_PAGE_TITLE = "status_page_title"
META_KEY_STATUS_PAGE_NOTICE_TEXT = "status_page_notice_text"
META_KEY_STATUS_PAGE_NOTICE_LEVEL = "status_page_notice_level"
