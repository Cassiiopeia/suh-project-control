import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/index.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import { createEnvironment, createSignedHeartbeatRequest } from '../test_support/fakes.js';

const ORIGIN = 'https://status.suhsaechan.kr';

test('GET /, /api/status.json은 공개 페이지 준비 전 503', async () => {
  const environment = createEnvironment(new FakeD1Database());
  for (const path of ['/', '/api/status.json']) {
    const response = await worker.fetch(new Request(`${ORIGIN}${path}`), environment, {});
    assert.equal(response.status, 503, path);
    assert.equal(await response.text(), 'status page pending');
  }
});

test('알 수 없는 경로·메서드는 404', async () => {
  const environment = createEnvironment(new FakeD1Database());
  const cases = [new Request(`${ORIGIN}/admin`), new Request(`${ORIGIN}/api/heartbeat`), new Request(`${ORIGIN}/`, { method: 'POST' })];
  for (const request of cases) {
    const response = await worker.fetch(request, environment, {});
    assert.equal(response.status, 404, `${request.method} ${request.url}`);
  }
});

test('POST /api/heartbeat는 심박 처리로 간다', async (context) => {
  context.mock.method(console, 'warn', () => {});
  const database = new FakeD1Database();
  const request = await createSignedHeartbeatRequest({ config_version: 'v1', public_incidents: [] }, Date.now());
  const response = await worker.fetch(request, createEnvironment(database), {});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { need_config: true });
  assert.notEqual(database.metaValue('last_heartbeat_at'), null);
});

test('처리 중 예외는 500 JSON (오류 문구 미노출)', async (context) => {
  const errorMock = context.mock.method(console, 'error', () => {});
  const database = new FakeD1Database();
  database.prepare = () => { throw new Error('secret internal detail'); };
  const request = await createSignedHeartbeatRequest({ config_version: 'v1' }, Date.now());
  const response = await worker.fetch(request, createEnvironment(database), {});
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { error: 'internal' });
  assert.equal(errorMock.mock.calls.some((call) => String(call.arguments.join(' ')).includes('secret internal detail')), false);
});

test('scheduled는 waitUntil로 크론 작업을 넘긴다', async () => {
  const pending = [];
  worker.scheduled({ scheduledTime: Date.now(), cron: '* * * * *' }, createEnvironment(new FakeD1Database()),
    { waitUntil: (promise) => pending.push(promise) });
  assert.equal(pending.length, 1);
  await pending[0];
});
