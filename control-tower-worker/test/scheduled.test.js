import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import { handleHeartbeat } from '../src/heartbeat.js';
import { runScheduled } from '../src/scheduled.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import {
  BASE_MILLISECONDS, TEST_WEBHOOK_URL, createEnvironment, createFakeFetch, createSignedHeartbeatRequest, webhookCalls,
} from '../test_support/fakes.js';

const SECOND_MILLISECONDS = 1000;
const MINUTE_MILLISECONDS = 60 * SECOND_MILLISECONDS;
const DAY_MILLISECONDS = 24 * 60 * MINUTE_MILLISECONDS;
// 2026-11-04 KST 23:58 (= 14:58Z)
const BEFORE_KST_MIDNIGHT_MILLISECONDS = Date.UTC(2026, 10, 4, 14, 58);
const SILENCE_TEXT = '관제소 심박 끊김(마지막 09:00 KST). 집 인터넷, Windows 서버, NAS 중 하나 장애 가능';

let database;
let environment;

beforeEach((context) => {
  database = new FakeD1Database();
  environment = createEnvironment(database);
  context.mock.method(console, 'warn', () => {});
  context.mock.method(console, 'log', () => {});
  context.mock.method(console, 'error', () => {});
});

function service(id, overrides = {}) {
  return {
    id, name: id, project_id: 'elum', status: 'active', is_public: true,
    external: { url: `https://${id}.example.com/`, expect: [], timeout_seconds: 10 }, ...overrides,
  };
}

function storeConfig(services, alert = { failures_to_down: 3, slow_milliseconds: 5000 }) {
  database.setMetaValue('config_json', JSON.stringify({ alert, projects: [], services, maintenance: [] }));
  database.setMetaValue('config_version', 'v1');
}

/** 서비스 상태 코드 표 + 웹훅 상태 코드로 응답하는 fetch */
function routedFetch(statusByHost = {}, webhookStatus = 204) {
  return createFakeFetch((url) => {
    if (url === TEST_WEBHOOK_URL) return new Response(null, { status: webhookStatus });
    return new Response('ignored body', { status: statusByHost[new URL(url).host] ?? 200 });
  });
}

function checkRunCount() {
  return database.query('SELECT COUNT(*) AS count FROM check_run')[0].count;
}

test('설정이 없으면 점검·기록 없이 심박 감시만 한다', async () => {
  database.setMetaValue('last_heartbeat_at', new Date(BASE_MILLISECONDS).toISOString());
  const fakeFetch = routedFetch();
  await runScheduled(environment, BASE_MILLISECONDS + 4 * MINUTE_MILLISECONDS, fakeFetch);
  assert.equal(checkRunCount(), 0);
  assert.equal(fakeFetch.calls.length, 1);
  assert.equal(webhookCalls(fakeFetch).length, 1);
});

test('점검 결과를 check_run 1행·최근 결과·오늘 집계로 기록한다', async () => {
  storeConfig([service('elum-api'), service('elum-web'), service('internal-only', { external: null })]);
  await runScheduled(environment, BASE_MILLISECONDS, routedFetch({ 'elum-web.example.com': 503 }));

  const rows = database.query('SELECT checked_at, results_json FROM check_run');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].checked_at, '2026-11-04T00:00:00.000Z');
  const results = JSON.parse(rows[0].results_json);
  assert.deepEqual(Object.keys(results).sort(), ['elum-api', 'elum-web']);
  assert.deepEqual({ ...results['elum-web'], latency_milliseconds: 0 },
    { is_ok: false, is_slow: false, status_code: 503, latency_milliseconds: 0, error: null });

  assert.deepEqual(JSON.parse(database.metaValue('recent_results_json')), {
    'elum-api': [{ is_ok: true, is_slow: false, checked_at: '2026-11-04T00:00:00.000Z' }],
    'elum-web': [{ is_ok: false, is_slow: false, checked_at: '2026-11-04T00:00:00.000Z' }],
  });
  assert.deepEqual(JSON.parse(database.metaValue('today_rollup_json')), {
    day: '2026-11-04', services: { 'elum-api': [1, 1], 'elum-web': [1, 0] },
  });
});

test('최근 결과는 최신순으로 failures_to_down(최소 3)개만 남긴다', async () => {
  storeConfig([service('elum-api')]);
  for (let minute = 0; minute < 5; minute += 1) {
    await runScheduled(environment, BASE_MILLISECONDS + minute * MINUTE_MILLISECONDS, routedFetch());
  }
  const recent = JSON.parse(database.metaValue('recent_results_json'))['elum-api'];
  assert.deepEqual(recent.map((entry) => entry.checked_at),
    ['2026-11-04T00:04:00.000Z', '2026-11-04T00:03:00.000Z', '2026-11-04T00:02:00.000Z']);

  storeConfig([service('elum-api')], { failures_to_down: 1, slow_milliseconds: 5000 });
  await runScheduled(environment, BASE_MILLISECONDS + 5 * MINUTE_MILLISECONDS, routedFetch());
  assert.equal(JSON.parse(database.metaValue('recent_results_json'))['elum-api'].length, 3);

  storeConfig([service('elum-api')], { failures_to_down: 5, slow_milliseconds: 5000 });
  await runScheduled(environment, BASE_MILLISECONDS + 6 * MINUTE_MILLISECONDS, routedFetch());
  assert.equal(JSON.parse(database.metaValue('recent_results_json'))['elum-api'].length, 4);
});

test('KST 날짜가 바뀌면 전날 집계를 daily_rollup에 1회만 기록한다', async () => {
  storeConfig([service('elum-api'), service('elum-web')]);
  const statusByHost = { 'elum-web.example.com': 503 };
  for (let minute = 0; minute < 4; minute += 1) {
    await runScheduled(environment, BEFORE_KST_MIDNIGHT_MILLISECONDS + minute * MINUTE_MILLISECONDS, routedFetch(statusByHost));
  }

  const rollups = database.query('SELECT day, service_id, total, ok FROM daily_rollup ORDER BY service_id');
  assert.deepEqual(rollups, [
    { day: '2026-11-04', service_id: 'elum-api', total: 2, ok: 2 },
    { day: '2026-11-04', service_id: 'elum-web', total: 2, ok: 0 },
  ]);
  assert.equal(database.metaValue('last_rollup_day'), '2026-11-04');
  const rollupLogCount = console.log.mock.calls
    .filter((call) => String(call.arguments[0]).includes('daily rollup written')).length;
  assert.equal(rollupLogCount, 1);
  assert.deepEqual(JSON.parse(database.metaValue('today_rollup_json')), {
    day: '2026-11-05', services: { 'elum-api': [2, 2], 'elum-web': [2, 0] },
  });
});

test('심박 3분 초과면 비상 알림 1회, 끊긴 동안 반복 없음, 다음 심박에서 복구 1회', async () => {
  database.setMetaValue('last_heartbeat_at', new Date(BASE_MILLISECONDS).toISOString());

  const atLimit = routedFetch();
  await runScheduled(environment, BASE_MILLISECONDS + 180 * SECOND_MILLISECONDS, atLimit);
  assert.equal(webhookCalls(atLimit).length, 0);

  const silent = routedFetch();
  await runScheduled(environment, BASE_MILLISECONDS + 181 * SECOND_MILLISECONDS, silent);
  const sent = webhookCalls(silent);
  assert.equal(sent.length, 1);
  assert.deepEqual(JSON.parse(sent[0].init.body), { content: SILENCE_TEXT, allowed_mentions: { parse: [] } });
  assert.equal(database.metaValue('emergency_state'), 'down');
  assert.equal(database.metaValue('emergency_since'), '2026-11-04T00:00:00.000Z');

  const stillSilent = routedFetch();
  await runScheduled(environment, BASE_MILLISECONDS + 4 * MINUTE_MILLISECONDS, stillSilent);
  assert.equal(webhookCalls(stillSilent).length, 0);

  const recoveredAt = BASE_MILLISECONDS + 10 * MINUTE_MILLISECONDS;
  const recoveryFetch = routedFetch();
  const request = await createSignedHeartbeatRequest({ config_version: 'v1', public_incidents: [] }, recoveredAt);
  await handleHeartbeat(request, environment, recoveredAt, recoveryFetch);
  assert.equal(JSON.parse(webhookCalls(recoveryFetch)[0].init.body).content, '관제소 심박 복구 (끊김 09:00 ~ 09:10 KST)');
  assert.equal(database.metaValue('emergency_state'), 'ok');

  const afterRecovery = routedFetch();
  await runScheduled(environment, recoveredAt + MINUTE_MILLISECONDS, afterRecovery);
  assert.equal(webhookCalls(afterRecovery).length, 0);
});

test('심박을 한 번도 받지 않았으면 비상 알림 없음', async () => {
  const fakeFetch = routedFetch();
  await runScheduled(environment, BASE_MILLISECONDS, fakeFetch);
  assert.equal(webhookCalls(fakeFetch).length, 0);
  assert.equal(database.metaValue('emergency_state'), null);
});

test('비상 웹훅이 실패하면 상태를 바꾸지 않고 다음 분에 다시 보낸다', async () => {
  database.setMetaValue('last_heartbeat_at', new Date(BASE_MILLISECONDS).toISOString());
  const failing = routedFetch({}, 500);
  await runScheduled(environment, BASE_MILLISECONDS + 4 * MINUTE_MILLISECONDS, failing);
  assert.equal(webhookCalls(failing).length, 1);
  assert.notEqual(database.metaValue('emergency_state'), 'down');

  const retried = routedFetch();
  await runScheduled(environment, BASE_MILLISECONDS + 5 * MINUTE_MILLISECONDS, retried);
  assert.equal(webhookCalls(retried).length, 1);
  assert.equal(database.metaValue('emergency_state'), 'down');
});

test('웹훅 주소가 없으면 호출하지 않고 다음 분에 다시 시도한다', async () => {
  database.setMetaValue('last_heartbeat_at', new Date(BASE_MILLISECONDS).toISOString());
  const fakeFetch = routedFetch();
  await runScheduled({ ...environment, DISCORD_EMERGENCY_WEBHOOK_URL: undefined }, BASE_MILLISECONDS + 4 * MINUTE_MILLISECONDS, fakeFetch);
  assert.equal(fakeFetch.calls.length, 0);
  assert.equal(database.metaValue('emergency_state'), null);
});

test('7일 지난 check_run은 매시 정각에만 지운다', async () => {
  storeConfig([service('elum-api')]);
  const oldCheckedAt = new Date(BASE_MILLISECONDS - 7 * DAY_MILLISECONDS - MINUTE_MILLISECONDS).toISOString();
  const keptCheckedAt = new Date(BASE_MILLISECONDS - 7 * DAY_MILLISECONDS + MINUTE_MILLISECONDS).toISOString();
  database.query('INSERT INTO check_run (checked_at, results_json) VALUES (?, ?)', oldCheckedAt, '{}');
  database.query('INSERT INTO check_run (checked_at, results_json) VALUES (?, ?)', keptCheckedAt, '{}');

  await runScheduled(environment, BASE_MILLISECONDS + MINUTE_MILLISECONDS, routedFetch());
  assert.equal(checkRunCount(), 3);

  await runScheduled(environment, BASE_MILLISECONDS, routedFetch());
  const remaining = database.query('SELECT checked_at FROM check_run ORDER BY id').map((row) => row.checked_at);
  assert.equal(remaining.includes(oldCheckedAt), false);
  assert.equal(remaining.includes(keptCheckedAt), true);
});

test('점검 기록이 실패해도 심박 감시는 돈다', async () => {
  storeConfig([service('elum-api')]);
  database.setMetaValue('last_heartbeat_at', new Date(BASE_MILLISECONDS).toISOString());
  database.batch = async () => { throw new Error('D1 unavailable'); };
  const fakeFetch = routedFetch();
  await runScheduled(environment, BASE_MILLISECONDS + 4 * MINUTE_MILLISECONDS, fakeFetch);
  assert.equal(webhookCalls(fakeFetch).length, 1);
});
