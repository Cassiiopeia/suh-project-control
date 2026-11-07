import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  CHECK_START_DEADLINE_MILLISECONDS, MAXIMUM_CHECKED_SERVICES, MAXIMUM_CONCURRENT_CHECKS, isStatusOk, runChecks,
  selectCheckTargets,
} from '../src/checks.js';
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

/** 비동기 조건 대기 (setImmediate 반복, 상한 넘으면 실패: 회귀 시 멈추지 않고 실패) */
async function waitUntil(isReady, maximumTurns = 200) {
  for (let turn = 0; turn < maximumTurns; turn += 1) {
    if (isReady()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  throw new Error('condition not reached');
}

/** 테스트가 직접 응답을 풀어 주는 fetch: 진행 중 요청 목록·최대 동시 수 기록 */
function createHeldFetch() {
  const heldRequests = [];
  let inFlightCount = 0;
  const fakeFetch = createFakeFetch((url) => new Promise((resolve) => {
    inFlightCount += 1;
    fakeFetch.maximumInFlightCount = Math.max(fakeFetch.maximumInFlightCount, inFlightCount);
    heldRequests.push({
      url,
      release: (status = 200) => { inFlightCount -= 1; resolve(fakeResponse(status)); },
    });
  }));
  fakeFetch.maximumInFlightCount = 0;
  fakeFetch.heldRequests = heldRequests;
  return fakeFetch;
}

function numberedServices(count) {
  return Array.from({ length: count }, (_, index) => externalService(`service-${String(index).padStart(2, '0')}`));
}

function fakeResponse(status) {
  const response = { status, ok: status >= 200 && status < 300, isBodyCancelled: false };
  response.body = { cancel: async () => { response.isBodyCancelled = true; } };
  return response;
}

/** 서비스 1개 점검: 호출되는 순간 시계를 latency만큼 진행 */
async function runSingle(service, respond, latencyMilliseconds = 120) {
  let nowMilliseconds = 0;
  const fakeFetch = createFakeFetch((url, init) => {
    nowMilliseconds += latencyMilliseconds;
    return respond(url, init);
  });
  const results = await runChecks(configWith([service]), fakeFetch, () => nowMilliseconds);
  return { result: results[service.id], fakeFetch };
}

test('isStatusOk는 Python is_status_ok와 같은 표를 따른다 (Cloudflare 520~530 포함)', () => {
  const table = [
    [200, [], true], [401, [], true], [404, [], true], [500, [], true],
    [502, [], false], [503, [], false], [504, [], false],
    [519, [], true], [520, [], false], [521, [], false], [530, [], false], [531, [], true],
    [404, [200], false], [200, [200], true], [521, [521], true],
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
  const slow = await runSingle(externalService('a'), () => fakeResponse(200), SLOW_MILLISECONDS + 1);
  assert.deepEqual([slow.result.is_ok, slow.result.is_slow], [true, true]);
  const boundary = await runSingle(externalService('a'), () => fakeResponse(200), SLOW_MILLISECONDS);
  assert.equal(boundary.result.is_slow, false);
  const failing = await runSingle(externalService('a'), () => fakeResponse(503), SLOW_MILLISECONDS + 1);
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
    const { result } = await runSingle(externalService('a'), () => { throw thrownError; }, 40);
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

test('6개 이하 대상은 모두 동시에 시작한다', { timeout: 2000 }, async () => {
  const fakeFetch = createHeldFetch();
  const running = runChecks(configWith(numberedServices(3)), fakeFetch, () => 0);
  await waitUntil(() => fakeFetch.heldRequests.length === 3);
  fakeFetch.heldRequests.forEach((request) => request.release());
  assert.deepEqual(Object.keys(await running), ['service-00', 'service-01', 'service-02']);
});

test('작업 풀은 동시에 6개를 넘지 않고 끝난 자리에 다음 대상을 시작한다', { timeout: 2000 }, async (context) => {
  const timeoutMock = context.mock.method(AbortSignal, 'timeout');
  const fakeFetch = createHeldFetch();
  const running = runChecks(configWith(numberedServices(10)), fakeFetch, () => 0);

  await waitUntil(() => fakeFetch.heldRequests.length === MAXIMUM_CONCURRENT_CHECKS);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(MAXIMUM_CONCURRENT_CHECKS, 6);
  assert.equal(fakeFetch.heldRequests.length, 6);
  // 타임아웃 신호는 실제 시작한 요청 수만큼만
  assert.equal(timeoutMock.mock.calls.length, 6);

  for (let releasedCount = 0; releasedCount < 10; releasedCount += 1) {
    await waitUntil(() => fakeFetch.heldRequests.length > releasedCount);
    fakeFetch.heldRequests[releasedCount].release();
  }
  const results = await running;
  assert.equal(Object.keys(results).length, 10);
  assert.equal(fakeFetch.maximumInFlightCount, 6);
  assert.equal(timeoutMock.mock.calls.length, 10);
});

test('대기열에서 기다린 시간은 지연 시간에 넣지 않는다', { timeout: 2000 }, async () => {
  let nowMilliseconds = 0;
  const fakeFetch = createHeldFetch();
  const running = runChecks(configWith(numberedServices(7)), fakeFetch, () => nowMilliseconds);
  await waitUntil(() => fakeFetch.heldRequests.length === 6);

  nowMilliseconds = 1000;
  fakeFetch.heldRequests[0].release();
  await waitUntil(() => fakeFetch.heldRequests.length === 7);
  nowMilliseconds = 1200;
  fakeFetch.heldRequests.slice(1).forEach((request) => request.release());

  const results = await running;
  assert.equal(results['service-00'].latency_milliseconds, 1000);
  assert.equal(results['service-01'].latency_milliseconds, 1200);
  assert.equal(results['service-06'].latency_milliseconds, 200);
});

test('마감(50초)이 지나면 남은 대상은 시작하지 않고 결과도 없다', { timeout: 2000 }, async (context) => {
  const warnMock = context.mock.method(console, 'warn', () => {});
  let nowMilliseconds = 0;
  const fakeFetch = createHeldFetch();
  const running = runChecks(configWith(numberedServices(8)), fakeFetch, () => nowMilliseconds);
  await waitUntil(() => fakeFetch.heldRequests.length === 6);

  nowMilliseconds = CHECK_START_DEADLINE_MILLISECONDS;
  fakeFetch.heldRequests.forEach((request) => request.release(503));
  const results = await running;

  assert.equal(CHECK_START_DEADLINE_MILLISECONDS, 50000);
  assert.equal(fakeFetch.calls.length, 6);
  assert.deepEqual(Object.keys(results), ['service-00', 'service-01', 'service-02', 'service-03', 'service-04', 'service-05']);
  assert.equal('service-06' in results, false);
  assert.match(warnMock.mock.calls.at(-1).arguments[0], /deadline reached : 2 targets skipped/);
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
