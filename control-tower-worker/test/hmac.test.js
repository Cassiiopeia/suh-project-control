import assert from 'node:assert/strict';
import { test } from 'node:test';

import { sign, verify } from '../src/hmac.js';

const VECTOR_TIMESTAMP = 1793750400;
const VECTOR_BODY = '{"a":1}';
// hex(HMAC-SHA256('test-secret', '1793750400.{"a":1}')) — Flask test_control_tower_heartbeat.py와 같은 벡터
const EXPECTED_VECTOR_SIGNATURE = 'c21ffbba805fa20789178125ce878759ec5713384f5959d4230fcbbdd99614fc';

function signedHeaders(timestamp, signature) {
  return new Headers({ 'X-CT-Timestamp': String(timestamp), 'X-CT-Signature': signature });
}

test('sign은 Flask와 같은 고정 벡터를 만든다 (문자열·바이트 본문)', async () => {
  assert.equal(await sign('test-secret', VECTOR_TIMESTAMP, VECTOR_BODY), EXPECTED_VECTOR_SIGNATURE);
  const bodyBytes = new TextEncoder().encode(VECTOR_BODY);
  assert.equal(await sign('test-secret', VECTOR_TIMESTAMP, bodyBytes), EXPECTED_VECTOR_SIGNATURE);
});

test('verify는 오차 299초(앞뒤)와 300초를 허용하고 301초를 거부한다', async () => {
  const headers = signedHeaders(VECTOR_TIMESTAMP, EXPECTED_VECTOR_SIGNATURE);
  assert.equal(await verify('test-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP + 299), true);
  assert.equal(await verify('test-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP - 299), true);
  assert.equal(await verify('test-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP + 300), true);
  assert.equal(await verify('test-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP + 301), false);
  assert.equal(await verify('test-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP - 301), false);
});

test('verify는 대문자 hex 서명도 받는다', async () => {
  const headers = signedHeaders(VECTOR_TIMESTAMP, EXPECTED_VECTOR_SIGNATURE.toUpperCase());
  assert.equal(await verify('test-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP), true);
});

test('verify는 변조된 본문·서명·다른 비밀키를 거부한다', async () => {
  const headers = signedHeaders(VECTOR_TIMESTAMP, EXPECTED_VECTOR_SIGNATURE);
  assert.equal(await verify('test-secret', headers, '{"a":2}', VECTOR_TIMESTAMP), false);
  assert.equal(await verify('other-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP), false);
  const tamperedSignature = `0${EXPECTED_VECTOR_SIGNATURE.slice(1)}`;
  assert.equal(await verify('test-secret', signedHeaders(VECTOR_TIMESTAMP, tamperedSignature), VECTOR_BODY,
    VECTOR_TIMESTAMP), false);
});

test('verify는 헤더 누락·형식 오류·비밀키 미설정을 거부한다', async () => {
  const cases = [
    new Headers({ 'X-CT-Signature': EXPECTED_VECTOR_SIGNATURE }),
    new Headers({ 'X-CT-Timestamp': String(VECTOR_TIMESTAMP) }),
    signedHeaders('17937504OO', EXPECTED_VECTOR_SIGNATURE),
    signedHeaders(VECTOR_TIMESTAMP, 'not-hex'),
    signedHeaders(VECTOR_TIMESTAMP, EXPECTED_VECTOR_SIGNATURE.slice(2)),
  ];
  for (const headers of cases) {
    assert.equal(await verify('test-secret', headers, VECTOR_BODY, VECTOR_TIMESTAMP), false);
  }
  const headers = signedHeaders(VECTOR_TIMESTAMP, EXPECTED_VECTOR_SIGNATURE);
  assert.equal(await verify('', headers, VECTOR_BODY, VECTOR_TIMESTAMP), false);
  assert.equal(await verify(undefined, headers, VECTOR_BODY, VECTOR_TIMESTAMP), false);
});
