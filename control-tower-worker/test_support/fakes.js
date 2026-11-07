/**
 * 테스트 공통 가짜: 호출 기록 fetch, 서명된 심박 요청, 고정 시각
 */
import { sign } from '../src/hmac.js';

export const TEST_SECRET = 'test-secret';
export const TEST_WEBHOOK_URL = 'https://discord.test/api/webhooks/1/token';
export const HEARTBEAT_URL = 'https://status.suhsaechan.kr/api/heartbeat';
// 2026-11-04T00:00:00Z = KST 09:00
export const BASE_MILLISECONDS = Date.UTC(2026, 10, 4, 0, 0, 0);

/** 응답 함수로 동작하는 fetch (호출 url·init 기록) */
export function createFakeFetch(respond) {
  const calls = [];
  const fakeFetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return respond(String(url), init, calls.length);
  };
  fakeFetch.calls = calls;
  return fakeFetch;
}

/** 웹훅 호출만 골라냄 */
export function webhookCalls(fakeFetch) {
  return fakeFetch.calls.filter((call) => call.url === TEST_WEBHOOK_URL);
}

export function createEnvironment(database) {
  return { DB: database, HMAC_SECRET: TEST_SECRET, DISCORD_EMERGENCY_WEBHOOK_URL: TEST_WEBHOOK_URL };
}

/** 본문 객체 > 서명 헤더 붙은 POST /api/heartbeat */
export async function createSignedHeartbeatRequest(body, nowMilliseconds, secret = TEST_SECRET) {
  const rawBody = typeof body === 'string' ? body : JSON.stringify(body);
  const timestamp = Math.floor(nowMilliseconds / 1000);
  const signature = await sign(secret, timestamp, rawBody);
  return new Request(HEARTBEAT_URL, {
    method: 'POST',
    body: rawBody,
    headers: { 'content-type': 'application/json', 'X-CT-Timestamp': String(timestamp), 'X-CT-Signature': signature },
  });
}
