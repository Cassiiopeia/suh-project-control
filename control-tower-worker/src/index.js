/**
 * Worker 진입점: fetch 라우팅(POST /api/heartbeat, GET /·/api/status.json 공개 상태, GET 아이콘·robots·sitemap, 그 외 404), 1분 크론 > runScheduled
 */
import { handleHeartbeat } from './heartbeat.js';
import { jsonResponse, textResponse } from './http.js';
import { runScheduled } from './scheduled.js';
import { SITE_ASSET_PATHS, handleSiteAssetRequest } from './site_asset_route.js';
import { STATUS_PAGE_PATHS, getDefaultStatusCache, handleStatusRequest } from './status_route.js';

const HEARTBEAT_PATH = '/api/heartbeat';

/** 요청 > 경로·메서드별 처리 (처리 중 예외는 500, 오류 이름만 기록) */
async function routeRequest(request, environment, context) {
  const { pathname } = new URL(request.url);
  try {
    if (request.method === 'POST' && pathname === HEARTBEAT_PATH) {
      return await handleHeartbeat(request, environment, Date.now());
    }
    if (request.method === 'GET' && STATUS_PAGE_PATHS.has(pathname)) {
      return await handleStatusRequest(request, environment, Date.now(), getDefaultStatusCache(), context);
    }
    if (request.method === 'GET' && SITE_ASSET_PATHS.has(pathname)) {
      return handleSiteAssetRequest(pathname, Date.now());
    }
    return textResponse('not found', 404);
  } catch (error) {
    console.error(`[control-tower worker http] failed 500 : ${request.method} ${pathname} : ${error?.name ?? 'unknown'}`);
    return jsonResponse({ error: 'internal' }, 500);
  }
}

export default {
  fetch(request, environment, context) {
    return routeRequest(request, environment, context);
  },

  scheduled(event, environment, context) {
    context.waitUntil(runScheduled(environment, Date.now(), fetch));
  },
};
