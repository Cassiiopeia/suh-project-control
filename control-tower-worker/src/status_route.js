/**
 * GET / · /api/status.json: 캐시 조회 > (없으면) meta 1회 > 모델 > HTML|JSON > 60초 캐시
 * meta만 읽음 (check_run·daily_rollup 안 읽음, 무료 CPU·읽기 한도), 캐시 키는 쿼리 문자열 제거한 경로 (임의 쿼리로 캐시 우회 차단)
 * 캐시 오류는 경고만 남기고 캐시 없이 응답
 */
import { buildStatusModel, renderStatusPage } from './status_page.js';
import { MetaKey, getMetaValues, parseJsonObject } from './store.js';

export const STATUS_JSON_PATH = '/api/status.json';
export const STATUS_PAGE_PATHS = new Set(['/', STATUS_JSON_PATH]);

// 응답 캐시 시간 (초)
const STATUS_CACHE_SECONDS = 60;
// 공개 응답 보안 헤더: 스크립트·외부 자원·프레임 삽입 전부 차단
const STATUS_SECURITY_HEADERS = Object.freeze({
  'x-content-type-options': 'nosniff',
  'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; frame-ancestors 'none'",
  'referrer-policy': 'no-referrer',
});

/** Workers Cache API 기본 캐시 (Node 테스트 등 없으면 null) */
export function getDefaultStatusCache() {
  return typeof caches === 'undefined' ? null : caches.default;
}

/** 캐시 > 생성 > 캐시 저장 (context.waitUntil 있으면 응답 뒤에 저장) */
export async function handleStatusRequest(request, environment, nowMilliseconds, cache, context) {
  const url = new URL(request.url);
  const cacheKey = new Request(`${url.origin}${url.pathname}`);
  const cachedResponse = await matchCachedResponse(cache, cacheKey);
  if (cachedResponse) return cachedResponse;

  const model = await loadStatusModel(environment.DB, nowMilliseconds);
  const response = url.pathname === STATUS_JSON_PATH
    ? buildStatusResponse(JSON.stringify(model), 'application/json; charset=utf-8')
    : buildStatusResponse(renderStatusPage(model), 'text/html; charset=utf-8');
  if (cache) {
    const putPromise = Promise.resolve()
      .then(() => cache.put(cacheKey, response.clone()))
      .catch((error) => console.warn(`[control-tower worker status] cache write failed : ${error?.name ?? 'unknown'}`));
    if (typeof context?.waitUntil === 'function') context.waitUntil(putPromise);
    else await putPromise;
  }
  return response;
}

/** 캐시 조회 (캐시 없음·오류 > undefined) */
async function matchCachedResponse(cache, cacheKey) {
  if (!cache) return undefined;
  try {
    return await cache.match(cacheKey);
  } catch (error) {
    console.warn(`[control-tower worker status] cache read failed : ${error?.name ?? 'unknown'}`);
    return undefined;
  }
}

/** meta 6키 1회 > 공개 모델 (설정 손상은 경고 후 설정 없음으로) */
async function loadStatusModel(database, nowMilliseconds) {
  const meta = await getMetaValues(database, [
    MetaKey.CONFIG_JSON, MetaKey.RECENT_RESULTS_JSON, MetaKey.TODAY_ROLLUP_JSON,
    MetaKey.PUBLIC_ROLLUP_JSON, MetaKey.PUBLIC_INCIDENTS_JSON, MetaKey.LAST_HEARTBEAT_AT,
  ]);
  const config = parseJsonObject(meta[MetaKey.CONFIG_JSON]);
  if (config === null && meta[MetaKey.CONFIG_JSON] !== null) {
    console.warn('[control-tower worker status] config_json invalid : ignored');
  }
  return buildStatusModel(
    config,
    parseJsonObject(meta[MetaKey.RECENT_RESULTS_JSON]),
    parseJsonObject(meta[MetaKey.TODAY_ROLLUP_JSON]),
    parseJsonObject(meta[MetaKey.PUBLIC_ROLLUP_JSON]),
    parseJsonArray(meta[MetaKey.PUBLIC_INCIDENTS_JSON]),
    meta[MetaKey.LAST_HEARTBEAT_AT],
    nowMilliseconds,
  );
}

function buildStatusResponse(body, contentType) {
  return new Response(body, {
    status: 200,
    headers: { 'content-type': contentType, 'cache-control': `public, max-age=${STATUS_CACHE_SECONDS}`, ...STATUS_SECURITY_HEADERS },
  });
}

/** JSON 문자열 > 배열 (손상·배열 아님이면 빈 배열) */
function parseJsonArray(text) {
  if (typeof text !== 'string') return [];
  try {
    const value = JSON.parse(text);
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}
