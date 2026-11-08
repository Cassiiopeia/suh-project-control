import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import { handleHeartbeat } from '../src/heartbeat.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import {
  BASE_MILLISECONDS, HEARTBEAT_URL, createEnvironment, createFakeFetch, createSignedHeartbeatRequest, webhookCalls,
} from '../test_support/fakes.js';

const MINUTE_MILLISECONDS = 60 * 1000;
const SNAPSHOT = {
  alert: { failures_to_down: 3, slow_milliseconds: 5000 },
  projects: [{ id: 'elum', name: '이룸' }],
  services: [],
  maintenance: [],
};
const INCIDENTS = [{ service_id: 'elum-api', started_at: '2026-11-04T08:00:00+09:00' }];

let database;
let environment;

beforeEach((context) => {
  database = new FakeD1Database();
  environment = createEnvironment(database);
  context.mock.method(console, 'warn', () => {});
  context.mock.method(console, 'log', () => {});
});

function heartbeatBody(overrides = {}) {
  return { sent_at: '2026-11-04T09:00:00+09:00', config_version: 'v1', public_incidents: [], ...overrides };
}

async function sendHeartbeat(body, nowMilliseconds = BASE_MILLISECONDS, fakeFetch = createFakeFetch(() => new Response(null, { status: 204 }))) {
  const request = await createSignedHeartbeatRequest(body, nowMilliseconds);
  const response = await handleHeartbeat(request, environment, nowMilliseconds, fakeFetch);
  return { status: response.status, body: await response.json(), fakeFetch };
}

test('서명이 없거나 틀리면 401이고 아무것도 기록하지 않는다', async () => {
  const unsigned = new Request(HEARTBEAT_URL, { method: 'POST', body: JSON.stringify(heartbeatBody()) });
  const response = await handleHeartbeat(unsigned, environment, BASE_MILLISECONDS, createFakeFetch(() => null));
  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { error: 'unauthorized' });

  const stale = await createSignedHeartbeatRequest(heartbeatBody(), BASE_MILLISECONDS - 301 * 1000);
  const staleResponse = await handleHeartbeat(stale, environment, BASE_MILLISECONDS, createFakeFetch(() => null));
  assert.equal(staleResponse.status, 401);
  assert.equal(database.metaValue('last_heartbeat_at'), null);
});

test('1MB 넘는 본문은 413, 256KB 넘어도 1MB 이하면 받는다', async () => {
  const largeButAllowed = await sendHeartbeat(heartbeatBody({ padding: 'x'.repeat(300 * 1024) }));
  assert.equal(largeButAllowed.status, 200);
  database = new FakeD1Database();
  environment = createEnvironment(database);
  const body = heartbeatBody({ padding: 'x'.repeat(1024 * 1024) });
  const request = await createSignedHeartbeatRequest(body, BASE_MILLISECONDS);
  const response = await handleHeartbeat(request, environment, BASE_MILLISECONDS, createFakeFetch(() => null));
  assert.equal(response.status, 413);
  assert.equal(database.metaValue('last_heartbeat_at'), null);
});

test('서명은 맞지만 JSON이 아니거나 config_version이 없으면 400', async () => {
  for (const rawBody of ['not json', '[1,2]', JSON.stringify({ public_incidents: [] })]) {
    const request = await createSignedHeartbeatRequest(rawBody, BASE_MILLISECONDS);
    const response = await handleHeartbeat(request, environment, BASE_MILLISECONDS, createFakeFetch(() => null));
    assert.equal(response.status, 400, rawBody);
  }
});

test('need_config 왕복: 모르는 버전 > 설정 요청, 설정 실으면 저장, 같은 버전이면 요청 안 함', async () => {
  const first = await sendHeartbeat(heartbeatBody());
  assert.equal(first.status, 200);
  assert.deepEqual(first.body, { need_config: true });
  assert.equal(database.metaValue('last_heartbeat_at'), '2026-11-04T00:00:00.000Z');

  const second = await sendHeartbeat(heartbeatBody({ config: SNAPSHOT }));
  assert.deepEqual(second.body, { need_config: false, checked_at: null, external_results: {} });
  assert.deepEqual(JSON.parse(database.metaValue('config_json')), SNAPSHOT);
  assert.equal(database.metaValue('config_version'), 'v1');

  const third = await sendHeartbeat(heartbeatBody(), BASE_MILLISECONDS + MINUTE_MILLISECONDS);
  assert.equal(third.body.need_config, false);
  assert.equal(database.metaValue('last_heartbeat_at'), '2026-11-04T00:01:00.000Z');

  const changed = await sendHeartbeat(heartbeatBody({ config_version: 'v2' }));
  assert.deepEqual(changed.body, { need_config: true });
});

test('응답의 외부 결과는 최신 check_run 1행', async () => {
  const olderResults = { 'elum-api': { is_ok: false, is_slow: false, status_code: 503, latency_milliseconds: 80, error: null } };
  const latestResults = { 'elum-api': { is_ok: true, is_slow: false, status_code: 200, latency_milliseconds: 95, error: null } };
  database.query('INSERT INTO check_run (checked_at, results_json) VALUES (?, ?)', '2026-11-03T23:58:00.000Z', JSON.stringify(olderResults));
  database.query('INSERT INTO check_run (checked_at, results_json) VALUES (?, ?)', '2026-11-03T23:59:00.000Z', JSON.stringify(latestResults));
  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT }));

  const { body } = await sendHeartbeat(heartbeatBody());
  assert.deepEqual(body, { need_config: false, checked_at: '2026-11-03T23:59:00.000Z', external_results: latestResults });
});

test('설정 저장 로그는 기록이 성공한 뒤에만 남긴다', async () => {
  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT }));
  const storedLogCount = () => console.log.mock.calls
    .filter((call) => String(call.arguments[0]).includes('config stored')).length;
  assert.equal(storedLogCount(), 1);

  database.batch = async () => { throw new Error('D1 unavailable'); };
  const request = await createSignedHeartbeatRequest(heartbeatBody({ config: SNAPSHOT }), BASE_MILLISECONDS);
  await assert.rejects(handleHeartbeat(request, environment, BASE_MILLISECONDS, createFakeFetch(() => null)));
  assert.equal(storedLogCount(), 1);
});

test('공개 장애 목록을 저장한다', async () => {
  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT, public_incidents: INCIDENTS }));
  assert.deepEqual(JSON.parse(database.metaValue('public_incidents_json')), INCIDENTS);
});

test('비상 down 상태면 복구 웹훅을 1회만 보내고 ok로 바꾼다', async () => {
  database.setMetaValue('emergency_state', 'down');
  database.setMetaValue('emergency_since', '2026-11-03T23:57:00.000Z');
  database.setMetaValue('config_version', 'v1');

  const recoveredAt = BASE_MILLISECONDS + 5 * MINUTE_MILLISECONDS;
  const first = await sendHeartbeat(heartbeatBody(), recoveredAt);
  const sent = webhookCalls(first.fakeFetch);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(sent[0].init.body), {
    content: '관제소 심박 복구 (끊김 08:57 ~ 09:05 KST)', allowed_mentions: { parse: [] },
  });
  assert.equal(database.metaValue('emergency_state'), 'ok');

  const second = await sendHeartbeat(heartbeatBody(), recoveredAt + MINUTE_MILLISECONDS);
  assert.equal(webhookCalls(second.fakeFetch).length, 0);
});

test('복구 웹훅이 실패하면 down을 유지하고 다음 심박에서 다시 보낸다', async () => {
  database.setMetaValue('emergency_state', 'down');
  database.setMetaValue('emergency_since', '2026-11-03T23:57:00.000Z');
  database.setMetaValue('config_version', 'v1');

  const failing = await sendHeartbeat(heartbeatBody(), BASE_MILLISECONDS, createFakeFetch(() => new Response(null, { status: 500 })));
  assert.equal(failing.status, 200);
  assert.equal(webhookCalls(failing.fakeFetch).length, 1);
  assert.equal(database.metaValue('emergency_state'), 'down');

  const retried = await sendHeartbeat(heartbeatBody(), BASE_MILLISECONDS + MINUTE_MILLISECONDS);
  assert.equal(webhookCalls(retried.fakeFetch).length, 1);
  assert.equal(database.metaValue('emergency_state'), 'ok');
});

// 프로젝트 썸네일 심박 (base64 문자만 들어 있으면 내용은 임의 문자열로 충분)
const ICON_BASE64 = 'UklGRg==';

test('썸네일: 설정과 함께 온 project_icons를 전체 교체로 저장한다', async () => {
  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT, project_icons: { elum: ICON_BASE64, 'suh-ai': 'AAAA' } }));
  assert.deepEqual(JSON.parse(database.metaValue('project_icons_json')), { elum: ICON_BASE64, 'suh-ai': 'AAAA' });

  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT, config_version: 'v2', project_icons: { elum: 'BBBB' } }));
  assert.deepEqual(JSON.parse(database.metaValue('project_icons_json')), { elum: 'BBBB' }, 'full replace');
});

test('썸네일: 규칙 밖 항목은 조용히 제외하고 경고만 남긴다 (본문은 로그에 없음)', async () => {
  const tooLong = 'A'.repeat(40001);
  await sendHeartbeat(heartbeatBody({
    config: SNAPSHOT,
    project_icons: { elum: ICON_BASE64, 'Bad_ID': 'AAAA', 'x': 'AAAA', 'elum-long': tooLong, 'elum-bad': 'not base64!', 'elum-number': 12 },
  }));
  assert.deepEqual(JSON.parse(database.metaValue('project_icons_json')), { elum: ICON_BASE64 });
  const warnings = console.warn.mock.calls.map((call) => String(call.arguments.join(' ')));
  assert.ok(warnings.some((text) => text.includes('project icons rejected : 5')));
  assert.equal(warnings.some((text) => text.includes('not base64')), false);
});

test('썸네일: 50개를 넘으면 앞 50개만 받는다', async () => {
  const icons = Object.fromEntries(Array.from({ length: 60 }, (_, index) => [`project-${index}`, 'AAAA']));
  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT, project_icons: icons }));
  assert.equal(Object.keys(JSON.parse(database.metaValue('project_icons_json'))).length, 50);
});

test('썸네일: 설정이 없는 심박이나 묶음이 없는 설정은 기존 썸네일을 건드리지 않는다', async () => {
  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT, project_icons: { elum: ICON_BASE64 } }));
  const before = database.metaValue('project_icons_json');

  await sendHeartbeat(heartbeatBody({ project_icons: { other: 'AAAA' } }));
  assert.equal(database.metaValue('project_icons_json'), before, 'no config > untouched');

  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT, config_version: 'v2' }));
  assert.equal(database.metaValue('project_icons_json'), before, 'no project_icons > untouched');

  await sendHeartbeat(heartbeatBody({ config: SNAPSHOT, config_version: 'v3', project_icons: 'broken' }));
  assert.equal(database.metaValue('project_icons_json'), before, 'not an object > untouched');
});
