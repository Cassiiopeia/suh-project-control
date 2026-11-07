/**
 * 크론 집계 (순수 함수): 최근 결과 목록(최신순, 상한) 갱신, 오늘 집계 누적·KST 날짜 바뀌면 전날 마감
 * 공개 페이지가 check_run을 훑지 않도록 meta에 미리 계산해 둠 (무료 CPU 10ms 한도)
 */
import { isPlainObject } from './store.js';

// 최근 결과 최소 보관 수 (failures_to_down이 더 작아도 3개)
const MINIMUM_RECENT_RESULT_COUNT = 3;
const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** 최근 결과 보관 수 = max(failures_to_down, 3) */
export function recentResultLimit(config) {
  const failuresToDown = Math.floor(Number(config?.alert?.failures_to_down));
  return Number.isFinite(failuresToDown) ? Math.max(failuresToDown, MINIMUM_RECENT_RESULT_COUNT) : MINIMUM_RECENT_RESULT_COUNT;
}

/** 이번 결과를 맨 앞에 추가 > 상한까지 자름 (이번에 점검한 서비스만 남김) */
export function appendRecentResults(previousRecent, results, checkedAt, limit) {
  const recent = {};
  for (const [serviceId, result] of Object.entries(results)) {
    const previous = isPlainObject(previousRecent) && Array.isArray(previousRecent[serviceId]) ? previousRecent[serviceId] : [];
    recent[serviceId] = [{ is_ok: result.is_ok, is_slow: result.is_slow, checked_at: checkedAt }, ...previous].slice(0, limit);
  }
  return recent;
}

/**
 * 오늘 집계 진행: 저장 날짜 ≠ 오늘이면 저장분을 마감(finishedRollup) 후 새로 시작 > 이번 결과 누적
 * 반환 {todayRollup: {day, services: {id: [total, ok]}}, finishedRollup: 같은 모양 | null}
 */
export function advanceTodayRollup(storedRollup, results, today) {
  const validRollup = sanitizeRollup(storedRollup);
  const isSameDay = validRollup?.day === today;
  const services = isSameDay ? { ...validRollup.services } : {};
  for (const [serviceId, result] of Object.entries(results)) {
    const [total, okCount] = services[serviceId] ?? [0, 0];
    services[serviceId] = [total + 1, okCount + (result.is_ok ? 1 : 0)];
  }
  return {
    todayRollup: { day: today, services },
    finishedRollup: validRollup !== null && !isSameDay ? validRollup : null,
  };
}

/** 저장된 집계 형태 검사: day 형식, [total, ok] 0 이상 정수 쌍만 남김, 잘못되면 null */
function sanitizeRollup(storedRollup) {
  if (!isPlainObject(storedRollup) || !DAY_PATTERN.test(String(storedRollup.day))) return null;
  const services = {};
  if (isPlainObject(storedRollup.services)) {
    for (const [serviceId, counts] of Object.entries(storedRollup.services)) {
      if (isValidCountPair(counts)) services[serviceId] = [counts[0], counts[1]];
    }
  }
  return { day: storedRollup.day, services };
}

function isValidCountPair(counts) {
  return Array.isArray(counts) && counts.length === 2
    && counts.every((count) => Number.isInteger(count) && count >= 0) && counts[1] <= counts[0];
}
