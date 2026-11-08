/**
 * POST /api/heartbeat: 크기 제한 > 서명 검증 > 본문 검사 > meta 기록(심박 시각·설정·프로젝트 썸네일·공개 장애) > 비상 복구 > 설정 요청 또는 최신 외부 결과 응답
 * Flask가 Worker를 부르는 단방향 (Worker는 Flask를 호출하지 않음)
 */
import { recoverIfEmergencyDown } from './emergency.js';
import { verify } from './hmac.js';
import { jsonResponse } from './http.js';
import { sanitizeProjectIcons } from './project_icons.js';
import { MetaKey, getLatestCheckRun, getMetaValues, isPlainObject, setMetaValues } from './store.js';
import { MILLISECONDS_PER_SECOND, toIsoUtc } from './time.js';

// 심박 본문 최대 크기 (1MB, 설정과 프로젝트 썸네일이 함께 실림)
export const MAXIMUM_BODY_BYTES = 1024 * 1024;

/** 심박 1건 처리 > Response (401 서명 실패, 400 본문 오류, 413 크기 초과) */
export async function handleHeartbeat(request, environment, nowMilliseconds, fetchImpl = fetch) {
  const rawBody = await readBodyWithinLimit(request, MAXIMUM_BODY_BYTES);
  if (rawBody === null) {
    console.warn('[control-tower worker heartbeat] rejected 413 : body too large');
    return jsonResponse({ error: 'payload_too_large' }, 413);
  }
  const isSignatureValid = await verify(
    environment.HMAC_SECRET, request.headers, rawBody, Math.floor(nowMilliseconds / MILLISECONDS_PER_SECOND),
  );
  if (!isSignatureValid) {
    console.warn('[control-tower worker heartbeat] rejected 401 : invalid signature or timestamp');
    return jsonResponse({ error: 'unauthorized' }, 401);
  }
  const body = parseHeartbeatBody(rawBody);
  if (body === null) {
    console.warn('[control-tower worker heartbeat] rejected 400 : invalid body');
    return jsonResponse({ error: 'bad_request' }, 400);
  }

  const database = environment.DB;
  const storedMeta = await getMetaValues(database, [
    MetaKey.EMERGENCY_STATE, MetaKey.EMERGENCY_SINCE, MetaKey.CONFIG_VERSION, MetaKey.PUBLIC_INCIDENTS_JSON,
  ]);
  const { updates, isConfigNeeded } = planMetaUpdates(body, storedMeta, nowMilliseconds);
  await setMetaValues(database, updates);
  if (MetaKey.CONFIG_JSON in updates) console.log('[control-tower worker heartbeat] config stored');
  await recoverIfEmergencyDown(environment, storedMeta, nowMilliseconds, fetchImpl);

  if (isConfigNeeded) return jsonResponse({ need_config: true });
  return jsonResponse(await buildExternalResultsBody(database));
}

/**
 * 기록할 meta 계산: 심박 시각(항상), 설정 실림 > 설정·버전·프로젝트 썸네일 저장, 버전 다름 > 설정 요청, 공개 장애(바뀐 경우만)
 */
function planMetaUpdates(body, storedMeta, nowMilliseconds) {
  const updates = { [MetaKey.LAST_HEARTBEAT_AT]: toIsoUtc(nowMilliseconds) };
  let isConfigNeeded = false;
  if (isPlainObject(body.config)) {
    updates[MetaKey.CONFIG_JSON] = JSON.stringify(body.config);
    updates[MetaKey.CONFIG_VERSION] = body.config_version;
    // 썸네일 묶음은 설정과 함께 올 때만 전체 교체 (묶음이 없으면 기존 유지)
    const projectIcons = sanitizeProjectIcons(body.project_icons);
    if (projectIcons !== null) updates[MetaKey.PROJECT_ICONS_JSON] = JSON.stringify(projectIcons);
  } else if (body.config_version !== storedMeta[MetaKey.CONFIG_VERSION]) {
    isConfigNeeded = true;
  }
  if (Array.isArray(body.public_incidents)) {
    const publicIncidentsJson = JSON.stringify(body.public_incidents);
    if (publicIncidentsJson !== storedMeta[MetaKey.PUBLIC_INCIDENTS_JSON]) {
      updates[MetaKey.PUBLIC_INCIDENTS_JSON] = publicIncidentsJson;
    }
  }
  return { updates, isConfigNeeded };
}

/** 최신 check_run 1행 > {need_config: false, checked_at, external_results} (없으면 null·빈 객체) */
async function buildExternalResultsBody(database) {
  const latestCheckRun = await getLatestCheckRun(database);
  return {
    need_config: false,
    checked_at: latestCheckRun?.checked_at ?? null,
    external_results: latestCheckRun?.results ?? {},
  };
}

/** 바이트 > 심박 본문 객체 (UTF-8·JSON 객체·config_version 문자열·config는 객체|null|없음), 아니면 null */
function parseHeartbeatBody(rawBody) {
  let body;
  try {
    body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(rawBody));
  } catch {
    return null;
  }
  if (!isPlainObject(body) || typeof body.config_version !== 'string') return null;
  if (body.config !== undefined && body.config !== null && !isPlainObject(body.config)) return null;
  return body;
}

/** 본문 스트림을 상한까지만 읽음 > Uint8Array, 초과하면 null (Content-Length 먼저 확인) */
async function readBodyWithinLimit(request, maximumBytes) {
  const declaredLength = Number(request.headers.get('content-length'));
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) return null;
  if (request.body === null) return new Uint8Array(0);

  const reader = request.body.getReader();
  const chunks = [];
  let totalBytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    totalBytes += value.byteLength;
    if (totalBytes > maximumBytes) {
      await reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const bodyBytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bodyBytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bodyBytes;
}
