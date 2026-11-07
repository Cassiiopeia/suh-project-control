/**
 * 비상 알림: 관제소 심박 끊김(3분 초과)·복구를 #관제-긴급 웹훅으로 1회씩
 * 상태 전환은 웹훅 성공 후에만 (실패면 다음 크론·다음 심박에서 재시도), 심박을 한 번도 못 받았으면 알림 없음
 */
import { cancelBody } from './http.js';
import { MetaKey, getMetaValues, setMetaValues } from './store.js';
import { parseIsoMilliseconds, toIsoUtc, toKstHourMinute } from './time.js';

// 심박 끊김 판정 기준 (초과 시 비상, 초)
export const HEARTBEAT_SILENCE_SECONDS = 180;
// emergency_state 값
export const EMERGENCY_STATE_OK = 'ok';
export const EMERGENCY_STATE_DOWN = 'down';
// 웹훅 요청 타임아웃 (밀리초)
const WEBHOOK_TIMEOUT_MILLISECONDS = 10 * 1000;
const MILLISECONDS_PER_SECOND = 1000;

export function buildSilenceMessage(lastHeartbeatMilliseconds) {
  return `관제소 심박 끊김(마지막 ${toKstHourMinute(lastHeartbeatMilliseconds)} KST). 집 인터넷, Windows 서버, NAS 중 하나 장애 가능`;
}

export function buildRecoveryMessage(sinceMilliseconds, nowMilliseconds) {
  return `관제소 심박 복구 (끊김 ${toKstHourMinute(sinceMilliseconds)} ~ ${toKstHourMinute(nowMilliseconds)} KST)`;
}

/** 크론 감시: 마지막 심박 > 180초 경과 && down 아님 > 끊김 웹훅 > 성공 시 down 기록 */
export async function watchHeartbeat(environment, nowMilliseconds, fetchImpl) {
  const database = environment.DB;
  const meta = await getMetaValues(database, [MetaKey.LAST_HEARTBEAT_AT, MetaKey.EMERGENCY_STATE]);
  const lastHeartbeatMilliseconds = parseIsoMilliseconds(meta[MetaKey.LAST_HEARTBEAT_AT]);
  if (lastHeartbeatMilliseconds === null || meta[MetaKey.EMERGENCY_STATE] === EMERGENCY_STATE_DOWN) return;
  const silenceSeconds = (nowMilliseconds - lastHeartbeatMilliseconds) / MILLISECONDS_PER_SECOND;
  if (silenceSeconds <= HEARTBEAT_SILENCE_SECONDS) return;

  const isSent = await postEmergencyMessage(environment, buildSilenceMessage(lastHeartbeatMilliseconds), fetchImpl);
  if (!isSent) return;
  await setMetaValues(database, {
    [MetaKey.EMERGENCY_STATE]: EMERGENCY_STATE_DOWN,
    [MetaKey.EMERGENCY_SINCE]: toIsoUtc(lastHeartbeatMilliseconds),
  });
  console.warn(`[control-tower worker emergency] heartbeat silent : ${Math.floor(silenceSeconds)}s, state ok -> down`);
}

/** 심박 수신 시 복구: down이면 복구 웹훅 > 성공 시 ok 기록 (storedMeta: 이번 요청에서 읽은 meta) */
export async function recoverIfEmergencyDown(environment, storedMeta, nowMilliseconds, fetchImpl) {
  if (storedMeta[MetaKey.EMERGENCY_STATE] !== EMERGENCY_STATE_DOWN) return;
  const sinceMilliseconds = parseIsoMilliseconds(storedMeta[MetaKey.EMERGENCY_SINCE]);
  const isSent = await postEmergencyMessage(environment, buildRecoveryMessage(sinceMilliseconds, nowMilliseconds), fetchImpl);
  if (!isSent) return;
  await setMetaValues(environment.DB, { [MetaKey.EMERGENCY_STATE]: EMERGENCY_STATE_OK });
  console.log('[control-tower worker emergency] heartbeat recovered : state down -> ok');
}

/** 웹훅 전송 > 성공 여부 (2xx만 성공, 멘션 차단, 주소·오류 문구 미기록) */
export async function postEmergencyMessage(environment, content, fetchImpl) {
  const webhookUrl = environment.DISCORD_EMERGENCY_WEBHOOK_URL;
  if (typeof webhookUrl !== 'string' || webhookUrl === '') {
    console.warn('[control-tower worker emergency] skipped : webhook not configured');
    return false;
  }
  try {
    const response = await fetchImpl(webhookUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ content, allowed_mentions: { parse: [] } }),
      signal: AbortSignal.timeout(WEBHOOK_TIMEOUT_MILLISECONDS),
    });
    cancelBody(response);
    if (!response.ok) {
      console.warn(`[control-tower worker emergency] rejected : status ${response.status}`);
      return false;
    }
    return true;
  } catch (error) {
    console.warn(`[control-tower worker emergency] failed : ${error?.name ?? 'unknown'}`);
    return false;
  }
}
