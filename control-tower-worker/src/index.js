/**
 * Worker 진입점: fetch 라우팅(POST /api/heartbeat, GET /·/api/status.json, 그 외 404), 1분 크론 > runScheduled
 */
import { handleHeartbeat } from './heartbeat.js';
import { jsonResponse, textResponse } from './http.js';
import { runScheduled } from './scheduled.js';

const HEARTBEAT_PATH = '/api/heartbeat';
// 공개 status 페이지 경로 (페이지 구현 전에는 503 자리표시)
const STATUS_PAGE_PATHS = new Set(['/', '/api/status.json']);

/** 요청 > 경로·메서드별 처리 (처리 중 예외는 500, 오류 이름만 기록) */
async function routeRequest(request, environment) {
  const { pathname } = new URL(request.url);
  try {
    if (request.method === 'POST' && pathname === HEARTBEAT_PATH) {
      return await handleHeartbeat(request, environment, Date.now());
    }
    if (request.method === 'GET' && STATUS_PAGE_PATHS.has(pathname)) {
      return textResponse('status page pending', 503);
    }
    return textResponse('not found', 404);
  } catch (error) {
    console.error(`[control-tower worker http] failed 500 : ${request.method} ${pathname} : ${error?.name ?? 'unknown'}`);
    return jsonResponse({ error: 'internal' }, 500);
  }
}

export default {
  fetch(request, environment) {
    return routeRequest(request, environment);
  },

  scheduled(event, environment, context) {
    context.waitUntil(runScheduled(environment, Date.now(), fetch));
  },
};
