/**
 * 시각 변환 공통: 밀리초 > ISO UTC, KST 날짜(YYYY-MM-DD), KST 시(YYYY-MM-DDTHH), KST HH:MM, KST 날짜 시:분, ISO > 밀리초
 */

export const MILLISECONDS_PER_SECOND = 1000;

// KST = UTC+9 (밀리초)
const KST_OFFSET_MILLISECONDS = 9 * 60 * 60 * 1000;
// 시각을 모를 때 표시
const UNKNOWN_HOUR_MINUTE = '--:--';

/** 밀리초 > ISO UTC 문자열 (예: 2026-11-04T00:00:00.000Z) */
export function toIsoUtc(milliseconds) {
  return new Date(milliseconds).toISOString();
}

/** 밀리초 > KST 날짜 (예: 2026-11-04) */
export function toKstDay(milliseconds) {
  return new Date(milliseconds + KST_OFFSET_MILLISECONDS).toISOString().slice(0, 10);
}

/** 밀리초 > KST 날짜·시 (예: 2026-11-04T09), 시간당 1회 처리 키 */
export function toKstHourKey(milliseconds) {
  return new Date(milliseconds + KST_OFFSET_MILLISECONDS).toISOString().slice(0, 13);
}

/** 밀리초 > KST 시:분 (예: 09:05), 모르면 --:-- */
export function toKstHourMinute(milliseconds) {
  if (!Number.isFinite(milliseconds)) return UNKNOWN_HOUR_MINUTE;
  return new Date(milliseconds + KST_OFFSET_MILLISECONDS).toISOString().slice(11, 16);
}

/** 밀리초 > KST 날짜 시:분 (예: 2026-11-04 09:05) */
export function toKstDateTime(milliseconds) {
  return new Date(milliseconds + KST_OFFSET_MILLISECONDS).toISOString().slice(0, 16).replace('T', ' ');
}

/** ISO 문자열 > 밀리초, 잘못되면 null */
export function parseIsoMilliseconds(text) {
  if (typeof text !== 'string') return null;
  const milliseconds = Date.parse(text);
  return Number.isFinite(milliseconds) ? milliseconds : null;
}
