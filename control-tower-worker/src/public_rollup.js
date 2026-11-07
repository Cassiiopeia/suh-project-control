/**
 * 공개 90일 집계 (순수 함수): 공개 대상 판정, 막대 기간, daily_rollup 행 + 방금 마감한 날 > public_rollup_json
 * 크론이 KST 하루 마감 때 1회 다시 만들어 meta에 둠 > 공개 페이지는 meta만 읽음 (원본은 daily_rollup)
 */
import { isPlainObject } from './store.js';
import { toKstDay } from './time.js';

// 막대 칸 수 (오늘 포함 일 수)
export const STATUS_DAY_COUNT = 90;
const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;
// 서비스 lifecycle 중 공개 대상
const VISIBLE_SERVICE_STATUS = 'active';

/** 공개 페이지 노출 대상: is_public && active */
export function isPubliclyVisibleService(service) {
  return isPlainObject(service) && service.is_public === true && service.status === VISIBLE_SERVICE_STATUS;
}

/** 오늘 포함 최근 90일 KST 날짜 (오래된 날 > 오늘) */
export function listStatusDays(nowMilliseconds) {
  return Array.from({ length: STATUS_DAY_COUNT },
    (_, index) => toKstDay(nowMilliseconds - (STATUS_DAY_COUNT - 1 - index) * MILLISECONDS_PER_DAY));
}

/** 첫 막대 날짜 (daily_rollup 조회 시작일) */
export function calculateFirstStatusDay(nowMilliseconds) {
  return toKstDay(nowMilliseconds - (STATUS_DAY_COUNT - 1) * MILLISECONDS_PER_DAY);
}

/**
 * 공개 집계 생성: 공개·active 서비스만, firstDay 이상 today 미만 (오늘은 today_rollup_json 몫)
 * finishedRollup({day, services: {id: [total, ok]}})은 아직 행에 없을 수 있어 덮어씀
 * 반환 {service_id: [[day, total, ok], ...]} 날짜 오름차순
 */
export function buildPublicRollup(config, rollupRows, finishedRollup, firstDay, today) {
  const publicServiceIds = new Set(
    (Array.isArray(config?.services) ? config.services : []).filter(isPubliclyVisibleService).map((service) => service.id),
  );
  const countsByDayByServiceId = new Map();
  const addCounts = (serviceId, day, total, okCount) => {
    if (!publicServiceIds.has(serviceId) || !(day >= firstDay && day < today)) return;
    const countsByDay = countsByDayByServiceId.get(serviceId) ?? new Map();
    countsByDay.set(day, [Number(total) || 0, Number(okCount) || 0]);
    countsByDayByServiceId.set(serviceId, countsByDay);
  };
  for (const row of Array.isArray(rollupRows) ? rollupRows : []) addCounts(row.service_id, row.day, row.total, row.ok);
  if (isPlainObject(finishedRollup?.services)) {
    for (const [serviceId, [total, okCount]] of Object.entries(finishedRollup.services)) {
      addCounts(serviceId, finishedRollup.day, total, okCount);
    }
  }

  const publicRollup = {};
  for (const [serviceId, countsByDay] of countsByDayByServiceId) {
    publicRollup[serviceId] = [...countsByDay.entries()]
      .sort(([leftDay], [rightDay]) => (leftDay < rightDay ? -1 : 1))
      .map(([day, [total, okCount]]) => [day, total, okCount]);
  }
  return publicRollup;
}
