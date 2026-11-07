import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MAXIMUM_CHECKED_SERVICES, isStatusOk, runChecks, selectCheckTargets } from '../src/checks.js';
import { createFakeFetch } from '../test_support/fakes.js';

const SLOW_MILLISECONDS = 5000;
const RESULT_KEYS = ['error', 'is_ok', 'is_slow', 'latency_milliseconds', 'status_code'];

function externalService(id, overrides = {}) {
  return {
    id, name: id, project_id: 'elum', status: 'active', is_public: true,
    external: { url: `https://${id}.example.com/health`, expect: [], timeout_seconds: 10 },
    ...overrides,
  };
}

function configWith(services) {
  return { alert: { failures_to_down: 3, slow_milliseconds: SLOW_MILLISECONDS }, projects: [], services, maintenance: [] };
}

/** 호출마다 다음 값을 돌려주는 시계 (마지막 값 유지) */
function sequenceClock(values) {
  let index = 0;
  return () => values[Math.min(index++, values.length - 1)];
}

function fakeResponse(status) {
  const response = { status, ok: status >= 200 && status < 300, isBodyCancelled: false };
  response.body = { cancel: async () => { response.isBodyCancelled = true; } };
  return response;
}

async function runSingle(service, respond, clockValues = [0, 120]) {
  const fakeFetch = createFakeFetch(respond);
  const results = await runChecks(configWith([service]), fakeFetch, sequenceClock(clockValues));
  return { result: results[service.id], fakeFetch };
}

test('isStatusOk는 Python is_status_ok와 같은 9행 표를 따른다', () => {
  const table = [
    [200, [], true], [401, [], true], [404, [], true], [500, [], true],
    [502, [], false], [503, [], false], [504, [], false],
    [404, [200], false], [200, [200], true],
  ];
  for (const [statusCode, expect, isExpectedOk] of table) {
    assert.equal(isStatusOk(statusCode, expect), isExpectedOk, `${statusCode} ${JSON.stringify(expect)}`);
  }
});

test('점검은 리다이렉트 미추적·타임아웃·user-agent로 호출하고 본문을 읽지 않고 취소한다', async (context) => {
  const timeoutMock = context.mock.method(AbortSignal, 'timeout');
  const response = fakeResponse(301);
  const service = externalService('elum-api', { external: { url: 'https://elum.example.com/', expect: [], timeout_seconds: 7 } });
  const { result, fakeFetch } = await runSingle(service, () => response);

  assert.equal(fakeFetch.calls.length, 1);
  const { url, init } = fakeFetch.calls[0];
  assert.equal(url, 'https://elum.example.com/');
  assert.equal(init.redirect, 'manual');
  assert.ok(init.signal instanceof AbortSignal);
  assert.equal(init.headers['user-agent'], 'suh-control-tower/1');
  assert.deepEqual(timeoutMock.mock.calls.map((call) => call.arguments[0]), [7000]);
  assert.equal(response.isBodyCancelled, true);
  assert.deepEqual(result, { is_ok: true, is_slow: false, status_code: 301, latency_milliseconds: 120, error: null });
});

test('정상 응답이 느리면 is_slow, 실패 응답은 느려도 is_slow 아님', async () => {
  const slow = await runSingle(externalService('a'), () => fakeResponse(200), [0, SLOW_MILLISECONDS + 1]);
  assert.deepEqual([slow.result.is_ok, slow.result.is_slow], [true, true]);
  const boundary = await runSingle(externalService('a'), () => fakeResponse(200), [0, SLOW_MILLISECONDS]);
  assert.equal(boundary.result.is_slow, false);
  const failing = await runSingle(externalService('a'), () => fakeResponse(503), [0, SLOW_MILLISECONDS + 1]);
  assert.deepEqual(failing.result, {
    is_ok: false, is_slow: false, status_code: 503, latency_milliseconds: SLOW_MILLISECONDS + 1, error: null,
  });
});

test('expect가 있으면 그 코드만 정상', async () => {
  const service = externalService('a', { external: { url: 'https://a.example.com', expect: [200], timeout_seconds: 5 } });
  const { result } = await runSingle(service, () => fakeResponse(404));
  assert.equal(result.is_ok, false);
  assert.equal(result.status_code, 404);
});

test('예외는 라벨로만 기록하고 오류 문구는 저장하지 않는다', async () => {
  const cases = [
    [new DOMException('The operation timed out.', 'TimeoutError'), 'timeout'],
    [new DOMException('This operation was aborted', 'AbortError'), 'timeout'],
    [new TypeError('SSL handshake failed'), 'tls_error'],
    [new Error('TLS peer certificate invalid'), 'tls_error'],
    [new TypeError('invalid certificate chain'), 'tls_error'],
    [new TypeError('Network connection lost.'), 'connection_error'],
    [new RangeError('secret detail 10.0.0.5'), 'error'],
  ];
  for (const [thrownError, expectedLabel] of cases) {
    const { result } = await runSingle(externalService('a'), () => { throw thrownError; }, [0, 40]);
    assert.deepEqual(result, {
      is_ok: false, is_slow: false, status_code: null, latency_milliseconds: 40, error: expectedLabel,
    }, thrownError.message);
    assert.deepEqual(Object.keys(result).sort(), RESULT_KEYS);
  }
});

test('external 있는 active·paused 서비스만 점검한다', () => {
  const services = [
    externalService('active-one'),
    externalService('paused-one', { status: 'paused' }),
    externalService('retired-one', { status: 'retired' }),
    externalService('no-external', { external: null }),
    { id: 'missing-external', status: 'active' },
  ];
  assert.deepEqual(selectCheckTargets(services).map((service) => service.id), ['active-one', 'paused-one']);
});

test('점검은 모두 동시에 시작한다 (Promise.all)', async () => {
  let startedCount = 0;
  let releaseAll;
  const released = new Promise((resolve) => { releaseAll = resolve; });
  const fakeFetch = createFakeFetch(async () => {
    startedCount += 1;
    if (startedCount === 3) releaseAll();
    await released;
    return fakeResponse(200);
  });
  const services = [externalService('a'), externalService('b'), externalService('c')];
  const results = await runChecks(configWith(services), fakeFetch, () => 0);
  assert.deepEqual(Object.keys(results).sort(), ['a', 'b', 'c']);
});

test('45개 넘으면 id 순으로 45개만 점검하고 경고를 남긴다', async (context) => {
  const warnMock = context.mock.method(console, 'warn', () => {});
  const services = Array.from({ length: 50 }, (_, index) => externalService(`service-${String(49 - index).padStart(2, '0')}`));
  const fakeFetch = createFakeFetch(() => fakeResponse(200));
  const results = await runChecks(configWith(services), fakeFetch, () => 0);

  assert.equal(MAXIMUM_CHECKED_SERVICES, 45);
  assert.equal(fakeFetch.calls.length, 45);
  const checkedIds = Object.keys(results).sort();
  assert.equal(checkedIds.length, 45);
  assert.equal(checkedIds[0], 'service-00');
  assert.equal(checkedIds[44], 'service-44');
  assert.equal(warnMock.mock.calls.length, 1);
  assert.match(warnMock.mock.calls[0].arguments[0], /^\[control-tower worker check\]/);
});
