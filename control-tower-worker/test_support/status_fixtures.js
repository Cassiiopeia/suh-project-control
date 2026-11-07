/**
 * 공개 status 테스트 공통 데이터: 공개·비공개·paused 서비스가 섞인 스냅샷, 최근 결과, 집계, 장애
 * 비공개 쪽에는 내부 IP·관리 도구 주소를 일부러 넣어 노출 여부 확인
 */

// 2026-11-07T03:00:00Z = KST 2026-11-07 12:00
export const STATUS_NOW_MILLISECONDS = Date.UTC(2026, 10, 7, 3, 0, 0);
export const TODAY_KST = '2026-11-07';

// 노출되면 안 되는 문자열 (비공개·paused 서비스, 내부 주소)
export const HIDDEN_STRINGS = Object.freeze([
  'elum-admin-hidden', '이룸 관리도구', 'http://192.168.0.10:5000/admin',
  'suh-paused-service', '일시중지 서비스', 'http://10.0.0.7:8080/',
  'secret-db', '비밀 DB', '비밀 프로젝트', 'https://secret-internal.example',
  'https://api.elum.example/health',
]);

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
    'elum-api': [recentResult(true, false, 0), recentResult(true, false, 1), recentResult(true, false, 2)],
    'elum-admin-hidden': [recentResult(false, false, 0), recentResult(false, false, 1), recentResult(false, false, 2)],
    'secret-db': [recentResult(false, false, 0), recentResult(false, false, 1), recentResult(false, false, 2)],
    'suh-paused-service': [recentResult(false, false, 0), recentResult(false, false, 1), recentResult(false, false, 2)],
    'suh-blog': [recentResult(true, false, 0)],
  };
}

export function createTodayRollup() {
  return { day: TODAY_KST, services: { 'elum-api': [720, 720], 'elum-admin-hidden': [720, 10], 'suh-blog': [720, 720] } };
}

export function createRollupRows() {
  return [
    { day: '2026-11-06', service_id: 'elum-api', total: 1440, ok: 1440 },
    { day: '2026-11-06', service_id: 'elum-admin-hidden', total: 1440, ok: 10 },
    { day: '2026-11-05', service_id: 'secret-db', total: 1440, ok: 0 },
  ];
}

export function createPublicIncidents() {
  return [
    { service_id: 'elum-api', started_at: '2026-11-06T05:00:00+00:00', ended_at: '2026-11-06T06:12:00+00:00' },
    { service_id: 'elum-admin-hidden', started_at: '2026-11-06T05:00:00+00:00', ended_at: null },
    { service_id: 'secret-db', started_at: '2026-11-05T05:00:00+00:00', ended_at: null },
  ];
}
