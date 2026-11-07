/**
 * 공개 status 테스트 공통 데이터: 공개·비공개·paused 서비스가 섞인 스냅샷, 최근 결과, 집계, 장애
 * 비공개 쪽에는 내부 IP·관리 도구 주소, 결과·장애에는 error·cause를 일부러 넣어 노출 여부 확인
 */
import { buildStatusModel } from '../src/status_page.js';

// 2026-11-07T03:00:00Z = KST 2026-11-07 12:00
export const STATUS_NOW_MILLISECONDS = Date.UTC(2026, 10, 7, 3, 0, 0);
export const TODAY_KST = '2026-11-07';
// 1분 전 심박 (지연 아님)
export const RECENT_HEARTBEAT_AT = new Date(STATUS_NOW_MILLISECONDS - 60000).toISOString();

// 노출되면 안 되는 문자열 (비공개·paused 서비스, 내부 주소)
export const HIDDEN_STRINGS = Object.freeze([
  'elum-admin-hidden', '이룸 관리도구', 'http://192.168.0.10:5000/admin',
  'suh-paused-service', '일시중지 서비스', 'http://10.0.0.7:8080/',
  'secret-db', '비밀 DB', '비밀 프로젝트', 'https://secret-internal.example',
  'https://api.elum.example/health',
  'LEAK_ERROR_DETAIL', 'LEAK_CAUSE_DETAIL',
]);
// 결과·장애에 섞어 넣는 내부 원인 문구 (공개 모델에 없어야 함)
const LEAK_ERROR = 'connection_error LEAK_ERROR_DETAIL 192.168.0.10';
const LEAK_CAUSE = 'LEAK_CAUSE_DETAIL NAS 10.0.0.2 디스크 가득 참';

export function createStatusConfig() {
  return {
    alert: { failures_to_down: 3, slow_milliseconds: 5000 },
    projects: [
      { id: 'elum', name: '이룸' },
      { id: 'secret', name: '비밀 프로젝트' },
      { id: 'suh', name: 'SUH' },
    ],
    services: [
      { id: 'elum-api', name: '이룸 API', project_id: 'elum', status: 'active', is_public: true,
        external: { url: 'https://api.elum.example/health', expect: [200], timeout_seconds: 10 } },
      { id: 'elum-admin-hidden', name: '이룸 관리도구', project_id: 'elum', status: 'active', is_public: false,
        external: { url: 'http://192.168.0.10:5000/admin', expect: [], timeout_seconds: 10 } },
      { id: 'elum-web', name: '이룸 웹', project_id: 'elum', status: 'active', is_public: true, external: null },
      { id: 'secret-db', name: '비밀 DB', project_id: 'secret', status: 'active', is_public: false,
        external: { url: 'https://secret-internal.example', expect: [], timeout_seconds: 10 } },
      { id: 'suh-paused-service', name: '일시중지 서비스', project_id: 'suh', status: 'paused', is_public: true,
        external: { url: 'http://10.0.0.7:8080/', expect: [], timeout_seconds: 10 } },
      { id: 'suh-blog', name: 'SUH 블로그', project_id: 'suh', status: 'active', is_public: true, external: null },
    ],
    maintenance: [],
  };
}

/** 결과 1건 (checked_at은 기준 시각에서 분 단위로 과거) */
export function recentResult(isOk, isSlow = false, minutesAgo = 0) {
  return { is_ok: isOk, is_slow: isSlow, checked_at: new Date(STATUS_NOW_MILLISECONDS - minutesAgo * 60000).toISOString() };
}

export function createRecentResults() {
  return {
    'elum-api': [recentResult(true, false, 0), { ...recentResult(false, false, 1), error: LEAK_ERROR }, recentResult(true, false, 2)],
    'elum-admin-hidden': [recentResult(false, false, 0), recentResult(false, false, 1), recentResult(false, false, 2)],
    'secret-db': [recentResult(false, false, 0), recentResult(false, false, 1), recentResult(false, false, 2)],
    'suh-paused-service': [recentResult(false, false, 0), recentResult(false, false, 1), recentResult(false, false, 2)],
    'suh-blog': [recentResult(true, false, 0)],
  };
}

export function createTodayRollup() {
  return { day: TODAY_KST, services: { 'elum-api': [720, 720], 'elum-admin-hidden': [720, 10], 'suh-blog': [720, 720] } };
}

/** public_rollup_json 형태 (비공개 서비스도 섞어 페이지 쪽 필터 확인) */
export function createPublicRollup() {
  return {
    'elum-api': [['2026-11-06', 1440, 1440]],
    'elum-admin-hidden': [['2026-11-06', 1440, 10]],
    'secret-db': [['2026-11-05', 1440, 0]],
  };
}

export function createPublicIncidents() {
  return [
    { service_id: 'elum-api', started_at: '2026-11-06T05:00:00+00:00', ended_at: '2026-11-06T06:12:00+00:00', cause: LEAK_CAUSE },
    { service_id: 'elum-admin-hidden', started_at: '2026-11-06T05:00:00+00:00', ended_at: null },
    { service_id: 'secret-db', started_at: '2026-11-05T05:00:00+00:00', ended_at: null },
  ];
}

/** 공통 데이터로 모델 생성, 지정한 키만 덮어씀 (null도 그대로 전달) */
export function buildFixtureModel(overrides = {}) {
  const pick = (key, createDefault) => (key in overrides ? overrides[key] : createDefault());
  return buildStatusModel(
    pick('config', createStatusConfig),
    pick('recentResults', createRecentResults),
    pick('todayRollup', createTodayRollup),
    pick('publicRollup', createPublicRollup),
    pick('publicIncidents', createPublicIncidents),
    pick('lastHeartbeatAt', () => RECENT_HEARTBEAT_AT),
    pick('nowMilliseconds', () => STATUS_NOW_MILLISECONDS),
  );
}
