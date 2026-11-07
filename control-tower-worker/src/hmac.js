/**
 * 심박 서명: hex(HMAC-SHA256(secret, "{timestamp}." + 본문 바이트)), Flask heartbeat_client.sign과 같은 규칙
 * 검증 3단계: 헤더 형식 > 시각 오차(300초) > 서명 (subtle.verify 상수 시간 비교)
 */

// 서명 헤더: unix 초 / hex 서명
export const TIMESTAMP_HEADER = 'X-CT-Timestamp';
export const SIGNATURE_HEADER = 'X-CT-Signature';
// 허용 시각 오차 (초, 경계 포함)
export const SIGNATURE_TOLERANCE_SECONDS = 300;

const TIMESTAMP_PATTERN = /^\d{1,12}$/;
// SHA-256 = 32바이트 = hex 64자
const SIGNATURE_PATTERN = /^[0-9a-f]{64}$/;
const HMAC_ALGORITHM = { name: 'HMAC', hash: 'SHA-256' };
const textEncoder = new TextEncoder();

/** 서명 생성 (rawBody: 문자열 또는 Uint8Array) */
export async function sign(secret, timestamp, rawBody) {
  const key = await importSecretKey(secret, ['sign']);
  const signature = await crypto.subtle.sign('HMAC', key, buildSignedMessage(String(timestamp), rawBody));
  return toHex(new Uint8Array(signature));
}

/** 서명 검증: 헤더 형식 > 시각 오차 > 서명 일치 (비밀키 미설정이면 항상 거부) */
export async function verify(secret, headers, rawBody, nowSeconds) {
  if (typeof secret !== 'string' || secret === '') return false;
  const timestampText = headers.get(TIMESTAMP_HEADER) ?? '';
  const signatureText = (headers.get(SIGNATURE_HEADER) ?? '').toLowerCase();
  if (!TIMESTAMP_PATTERN.test(timestampText) || !SIGNATURE_PATTERN.test(signatureText)) return false;
  if (Math.abs(nowSeconds - Number(timestampText)) > SIGNATURE_TOLERANCE_SECONDS) return false;
  const key = await importSecretKey(secret, ['verify']);
  return crypto.subtle.verify('HMAC', key, fromHex(signatureText), buildSignedMessage(timestampText, rawBody));
}

function importSecretKey(secret, usages) {
  return crypto.subtle.importKey('raw', textEncoder.encode(secret), HMAC_ALGORITHM, false, usages);
}

/** "{timestamp}." 바이트 + 본문 바이트 */
function buildSignedMessage(timestampText, rawBody) {
  const prefixBytes = textEncoder.encode(`${timestampText}.`);
  const bodyBytes = typeof rawBody === 'string' ? textEncoder.encode(rawBody) : rawBody;
  const message = new Uint8Array(prefixBytes.length + bodyBytes.length);
  message.set(prefixBytes, 0);
  message.set(bodyBytes, prefixBytes.length);
  return message;
}

function toHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** 소문자 hex(짝수 길이, 형식 검사 후) > 바이트 */
function fromHex(hexText) {
  const bytes = new Uint8Array(hexText.length / 2);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = parseInt(hexText.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}
