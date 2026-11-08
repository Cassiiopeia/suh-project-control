/**
 * 공개 status 모델 (순수 함수): 페이지 설정 > 공개·active 서비스만(스냅샷 배열 순서) > 현재 상태·90일 막대·가동률 > 묶음 요약 > 전체 배너·지연 여부·최근 14일 장애
 * 모델 = /api/status.json 본문 그대로 (점검 주소·원인 없음, 공개 서비스·프로젝트의 등록 파일 id는 포함), HTML은 status_render.js
 */
import { HEARTBEAT_SILENCE_SECONDS } from './emergency.js';
import { buildProjectIconUrl } from './project_icons.js';
import { isPubliclyVisibleService, listStatusDays } from './public_rollup.js';
import { readPageSettings } from './status_page_settings.js';
import { isPlainObject } from './store.js';
import { MILLISECONDS_PER_SECOND, parseIsoMilliseconds, toIsoUtc } from './time.js';

export { renderStatusPage } from './status_render.js';

// 서비스 현재 상태 (overall도 같은 값)
export const ServiceState = Object.freeze({
  UP: 'up', DEGRADED: 'degraded', DOWN: 'down', MAINTENANCE: 'maintenance', UNKNOWN: 'unknown',
});

// 최근 장애 표시 기간 (밀리초, 14일)
const INCIDENT_WINDOW_MILLISECONDS = 14 * 24 * 60 * 60 * 1000;
// 최근 장애 최대 표시 수
const MAXIMUM_INCIDENT_COUNT = 20;
const MILLISECONDS_PER_MINUTE = 60 * 1000;
// 연속 실패 down 판정 기본값 (스냅샷에 없을 때)
const DEFAULT_FAILURES_TO_DOWN = 3;
// 막대 색 경계 (만분율 정수 비교로 부동소수 오차 회피): ok ≥ 99.5%, warn ≥ 95%
const OK_LEVEL_MINIMUM_BASIS_POINTS = 9950;
const WARN_LEVEL_MINIMUM_BASIS_POINTS = 9500;
// 최신 결과가 이보다 오래되면 unknown (초, 크론 정지·점검 대상 제외 등)
const RECENT_RESULT_STALE_SECONDS = 5 * 60;
// 막대 등급 심각도 (클수록 나쁨), 오늘 막대 = 집계·실시간 중 나쁜 쪽
const SEVERITY_BY_LEVEL = Object.freeze({ none: 0, ok: 1, warn: 2, bad: 3 });
// 실시간 상태 > 오늘 막대 등급 (점검 중·확인 중은 집계 그대로)
const LIVE_LEVEL_BY_STATE = Object.freeze({
  [ServiceState.UP]: 'ok', [ServiceState.DEGRADED]: 'warn', [ServiceState.DOWN]: 'bad',
});

// 전체 배너 우선순위 (앞일수록 우선) > 문구
const OVERALL_PRIORITY = [ServiceState.DOWN, ServiceState.DEGRADED, ServiceState.MAINTENANCE, ServiceState.UP];
const OVERALL_MESSAGE_BY_STATE = Object.freeze({
  [ServiceState.DOWN]: '일부 서비스에 장애가 있습니다',
  [ServiceState.DEGRADED]: '일부 서비스가 느리게 응답하고 있습니다',
  [ServiceState.MAINTENANCE]: '일부 서비스 점검 중입니다',
  [ServiceState.UP]: '모든 서비스가 정상 작동 중입니다',
  [ServiceState.UNKNOWN]: '상태 정보를 불러오는 중입니다',
});

/**
 * 공개 모델 생성: 페이지 설정 > 공개 서비스 선별 > 프로젝트 묶음(서비스 행·묶음 요약) > 전체 배너 > 지연 여부 > 최근 장애
 * config = 스냅샷, recentResults = {id: [{is_ok, is_slow, checked_at}] 최신순}, todayRollup = {day, services: {id: [total, ok]}},
 * publicRollup = {id: [[day, total, ok]]} (오늘 제외), publicIncidents = [{service_id, started_at, ended_at}], lastHeartbeatAt = ISO | null
 */
export function buildStatusModel(config, recentResults, todayRollup, publicRollup, publicIncidents, lastHeartbeatAt, nowMilliseconds) {
  const visibleProjects = selectVisibleProjects(config);
  const days = listStatusDays(nowMilliseconds);
  const countsByDayByServiceId = indexDailyCounts(publicRollup, todayRollup);
  const maintenanceUntilById = indexMaintenanceUntil(config);
  const failuresToDown = readFailuresToDown(config);
  const safeRecentResults = isPlainObject(recentResults) ? recentResults : {};

  const projectGroups = visibleProjects.map(({ project, services }) => {
    const serviceRows = services.map((service) => {
      const recent = Array.isArray(safeRecentResults[service.id]) ? safeRecentResults[service.id] : [];
      const isUnderMaintenance = (maintenanceUntilById.get(service.id) ?? -Infinity) > nowMilliseconds;
      const state = isUnderMaintenance ? ServiceState.MAINTENANCE : judgeServiceState(recent, failuresToDown, nowMilliseconds);
      return { id: service.id, name: service.name, state, ...buildUptimeBars(days, countsByDayByServiceId.get(service.id), state) };
    });
    return summarizeProjectGroup(project, serviceRows);
  });
  const visibleServices = projectGroups.flatMap((group) => group.project.services);
  const overallState = judgeOverallState(visibleServices.map((service) => service.state));

  return {
    page: readPageSettings(config),
    overall: { state: overallState, message: OVERALL_MESSAGE_BY_STATE[overallState] },
    is_delayed: isHeartbeatDelayed(lastHeartbeatAt, nowMilliseconds),
    generated_at: toIsoUtc(nowMilliseconds),
    last_checked_at: findLastCheckedAt(visibleServices, safeRecentResults),
    projects: projectGroups.map((group) => group.project),
    incidents: buildIncidents(publicIncidents, visibleProjects, nowMilliseconds),
  };
}

/** 하루 점검 수·정상 수 > 막대 색 (ok | warn | bad | none) */
export function toUptimeLevel(total, okCount) {
  if (!(total > 0)) return 'none';
  const basisPoints = (okCount * 10000) / total;
  if (basisPoints >= OK_LEVEL_MINIMUM_BASIS_POINTS) return 'ok';
  if (basisPoints >= WARN_LEVEL_MINIMUM_BASIS_POINTS) return 'warn';
  return 'bad';
}

/** 정상 비율 > 퍼센트 소수 2자리 내림 (100% 미만을 100.00으로 올리지 않음), 점검 없으면 null */
function toUptimePercent(total, okCount) {
  return total > 0 ? Math.floor((okCount * 10000) / total) / 100 : null;
}

/** 공개·active 서비스만 > [{project, services}] 스냅샷 배열 순서 그대로 (Flask가 표시 순서로 보냄), 빈 프로젝트 제외 */
function selectVisibleProjects(config) {
  if (!isPlainObject(config) || !Array.isArray(config.services) || !Array.isArray(config.projects)) return [];
  const servicesByProjectId = new Map();
  for (const service of config.services) {
    if (!isPubliclyVisibleService(service)) continue;
    const services = servicesByProjectId.get(service.project_id) ?? [];
    services.push(service);
    servicesByProjectId.set(service.project_id, services);
  }
  return config.projects
    .filter((project) => isPlainObject(project) && servicesByProjectId.has(project.id))
    .map((project) => ({ project, services: servicesByProjectId.get(project.id) }));
}

/**
 * 묶음 요약: 서비스 행 > {project: {id, name, icon_url, state, uptime_percent, service_count, services}, totalCount, okCount}
 * 묶음 상태 = 서비스 상태 중 우선순위 최상위, 묶음 가동률 = 서비스 90일 합계 기준
 */
function summarizeProjectGroup(project, serviceRows) {
  let totalCount = 0;
  let okCount = 0;
  const services = serviceRows.map(({ totalCount: serviceTotalCount, okCount: serviceOkCount, ...service }) => {
    totalCount += serviceTotalCount;
    okCount += serviceOkCount;
    return service;
  });
  return {
    project: {
      id: project.id,
      name: project.name,
      icon_url: buildProjectIconUrl(project),
      state: judgeOverallState(services.map((service) => service.state)),
      uptime_percent: toUptimePercent(totalCount, okCount),
      service_count: services.length,
      services,
    },
    totalCount,
    okCount,
  };
}

/** 최근 결과(최신순) > unknown(없음·5분 넘게 오래됨) | down(최근 N회 모두 실패) | degraded(최근 1회 실패·느림) | up */
function judgeServiceState(recent, failuresToDown, nowMilliseconds) {
  if (recent.length === 0 || isRecentResultStale(recent[0], nowMilliseconds)) return ServiceState.UNKNOWN;
  const isDown = recent.length >= failuresToDown && recent.slice(0, failuresToDown).every((result) => result?.is_ok !== true);
  if (isDown) return ServiceState.DOWN;
  const newest = recent[0];
  if (newest?.is_ok !== true || newest?.is_slow === true) return ServiceState.DEGRADED;
  return ServiceState.UP;
}

/** 최신 결과 checked_at이 없거나 5분 초과 전이면 오래됨 */
function isRecentResultStale(newestResult, nowMilliseconds) {
  const checkedMilliseconds = parseIsoMilliseconds(newestResult?.checked_at);
  return checkedMilliseconds === null || nowMilliseconds - checkedMilliseconds > RECENT_RESULT_STALE_SECONDS * MILLISECONDS_PER_SECOND;
}

/** 서비스 상태 목록 > 우선순위 최상위 상태, 정상조차 없으면 unknown */
function judgeOverallState(states) {
  return OVERALL_PRIORITY.find((state) => states.includes(state)) ?? ServiceState.UNKNOWN;
}

function readFailuresToDown(config) {
  const failuresToDown = Math.floor(Number(config?.alert?.failures_to_down));
  return Number.isFinite(failuresToDown) && failuresToDown >= 1 ? failuresToDown : DEFAULT_FAILURES_TO_DOWN;
}

/** 점검 창 > {service_id: until 밀리초} (같은 서비스 여러 개면 가장 늦은 종료) */
function indexMaintenanceUntil(config) {
  const untilById = new Map();
  for (const maintenanceWindow of Array.isArray(config?.maintenance) ? config.maintenance : []) {
    const untilMilliseconds = parseIsoMilliseconds(maintenanceWindow?.until);
    if (untilMilliseconds === null) continue;
    const serviceId = maintenanceWindow.service_id;
    untilById.set(serviceId, Math.max(untilMilliseconds, untilById.get(serviceId) ?? -Infinity));
  }
  return untilById;
}

/** 공개 집계 + 오늘 집계(자기 날짜에 덮어씀, 전날 미마감분 포함) > Map(id > Map(day > [total, ok])) */
function indexDailyCounts(publicRollup, todayRollup) {
  const countsByDayByServiceId = new Map();
  const setCounts = (serviceId, day, total, okCount) => {
    const countsByDay = countsByDayByServiceId.get(serviceId) ?? new Map();
    countsByDay.set(day, [Number(total) || 0, Number(okCount) || 0]);
    countsByDayByServiceId.set(serviceId, countsByDay);
  };
  if (isPlainObject(publicRollup)) {
    for (const [serviceId, entries] of Object.entries(publicRollup)) {
      if (!Array.isArray(entries)) continue;
      for (const entry of entries) {
        if (Array.isArray(entry)) setCounts(serviceId, entry[0], entry[1], entry[2]);
      }
    }
  }
  if (isPlainObject(todayRollup) && isPlainObject(todayRollup.services)) {
    for (const [serviceId, counts] of Object.entries(todayRollup.services)) {
      if (Array.isArray(counts)) setCounts(serviceId, todayRollup.day, counts[0], counts[1]);
    }
  }
  return countsByDayByServiceId;
}

/**
 * 서비스 1개 > {uptime_percent: 90일 합계 기준, days: [{day, uptime_percent, level}], totalCount, okCount}
 * 오늘(마지막) 막대 등급 = 오늘 집계·실시간 상태 중 나쁜 쪽
 */
function buildUptimeBars(days, countsByDay, state) {
  let totalCount = 0;
  let okCount = 0;
  const bars = days.map((day) => {
    const [total, dayOkCount] = countsByDay?.get(day) ?? [0, 0];
    totalCount += total;
    okCount += dayOkCount;
    return { day, uptime_percent: toUptimePercent(total, dayOkCount), level: toUptimeLevel(total, dayOkCount) };
  });
  const todayBar = bars[bars.length - 1];
  const liveLevel = LIVE_LEVEL_BY_STATE[state];
  if (todayBar && liveLevel && SEVERITY_BY_LEVEL[liveLevel] > SEVERITY_BY_LEVEL[todayBar.level]) todayBar.level = liveLevel;
  return { uptime_percent: toUptimePercent(totalCount, okCount), days: bars, totalCount, okCount };
}

/** 마지막 심박이 3분 초과 전이면 지연 (심박 기록 없으면 지연 아님) */
function isHeartbeatDelayed(lastHeartbeatAt, nowMilliseconds) {
  const lastHeartbeatMilliseconds = parseIsoMilliseconds(lastHeartbeatAt);
  if (lastHeartbeatMilliseconds === null) return false;
  return nowMilliseconds - lastHeartbeatMilliseconds > HEARTBEAT_SILENCE_SECONDS * MILLISECONDS_PER_SECOND;
}

/** 공개 서비스 최근 결과 중 가장 늦은 checked_at (ISO UTC) | null */
function findLastCheckedAt(visibleServices, recentResults) {
  let latestMilliseconds = null;
  for (const service of visibleServices) {
    const newest = Array.isArray(recentResults[service.id]) ? recentResults[service.id][0] : null;
    const checkedMilliseconds = parseIsoMilliseconds(newest?.checked_at);
    if (checkedMilliseconds !== null && (latestMilliseconds === null || checkedMilliseconds > latestMilliseconds)) {
      latestMilliseconds = checkedMilliseconds;
    }
  }
  return latestMilliseconds === null ? null : toIsoUtc(latestMilliseconds);
}

/**
 * 공개 장애 > 공개 서비스만, 진행 중 또는 14일 안에 시작, 최신 시작순
 * 항목 {service_id, service_name, project_name, started_at, ended_at, is_ongoing, duration_minutes} (원인 없음)
 */
function buildIncidents(publicIncidents, visibleProjects, nowMilliseconds) {
  const namesByServiceId = new Map();
  for (const { project, services } of visibleProjects) {
    for (const service of services) namesByServiceId.set(service.id, { serviceName: service.name, projectName: project.name });
  }
  const incidents = [];
  for (const incident of Array.isArray(publicIncidents) ? publicIncidents : []) {
    const names = namesByServiceId.get(incident?.service_id);
    const startedMilliseconds = parseIsoMilliseconds(incident?.started_at);
    if (names === undefined || startedMilliseconds === null) continue;
    const endedMilliseconds = parseIsoMilliseconds(incident.ended_at);
    const isOngoing = endedMilliseconds === null;
    if (!isOngoing && startedMilliseconds < nowMilliseconds - INCIDENT_WINDOW_MILLISECONDS) continue;
    const durationMilliseconds = (isOngoing ? nowMilliseconds : endedMilliseconds) - startedMilliseconds;
    incidents.push({
      service_id: incident.service_id,
      service_name: names.serviceName,
      project_name: names.projectName,
      started_at: toIsoUtc(startedMilliseconds),
      ended_at: isOngoing ? null : toIsoUtc(endedMilliseconds),
      is_ongoing: isOngoing,
      duration_minutes: Math.max(0, Math.floor(durationMilliseconds / MILLISECONDS_PER_MINUTE)),
    });
  }
  return incidents.sort((left, right) => right.started_at.localeCompare(left.started_at)).slice(0, MAXIMUM_INCIDENT_COUNT);
}
