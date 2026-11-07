/**
 * 외부 점검: 대상 선별(external 있는 active·paused, 최대 45개) > 병렬 GET > 정상·slow 판정 > 실패 라벨 분류
 * 본문은 받지 않고 취소, 외부 오류 문구는 저장하지 않음 (Flask check_runner.py와 같은 판정)
 */
import { cancelBody } from './http.js';

// 기본 규칙에서 장애로 보는 상태 코드 (게이트웨이 계열)
const FAILURE_STATUS_CODES = [502, 503, 504];
// 크론 1회 외부 요청 상한 50개 중 점검 몫 (나머지는 비상 웹훅)
export const MAXIMUM_CHECKED_SERVICES = 45;
// 점검 대상 수명 상태 (retired 제외)
const CHECKED_SERVICE_STATUSES = new Set(['active', 'paused']);
// timeout_seconds·slow_milliseconds 누락 시 기본값
const DEFAULT_TIMEOUT_SECONDS = 10;
const DEFAULT_SLOW_MILLISECONDS = 5000;
const MILLISECONDS_PER_SECOND = 1000;
export const USER_AGENT = 'suh-control-tower/1';

// 실패 라벨 4종
export const ERROR_LABEL_TIMEOUT = 'timeout';
export const ERROR_LABEL_TLS = 'tls_error';
export const ERROR_LABEL_CONNECTION = 'connection_error';
export const ERROR_LABEL_UNKNOWN = 'error';
const TIMEOUT_ERROR_NAMES = new Set(['TimeoutError', 'AbortError']);
const TLS_ERROR_PATTERN = /SSL|TLS|[Cc]ertificate/;

/** 상태 코드 정상 판정: expect 있으면 그 코드만, 없으면 502·503·504 외 전부 */
export function isStatusOk(statusCode, expect) {
  if (Array.isArray(expect) && expect.length > 0) return expect.includes(statusCode);
  return !FAILURE_STATUS_CODES.includes(statusCode);
}

/** 점검 대상: external.url 있는 active·paused 서비스, id 순, 최대 45개 (초과 시 경고) */
export function selectCheckTargets(services) {
  const targets = (Array.isArray(services) ? services : [])
    .filter((service) => CHECKED_SERVICE_STATUSES.has(service?.status) && typeof service?.external?.url === 'string')
    .sort((left, right) => compareCodePoints(String(left.id), String(right.id)));
  if (targets.length > MAXIMUM_CHECKED_SERVICES) {
    console.warn(`[control-tower worker check] too many targets : ${targets.length} > ${MAXIMUM_CHECKED_SERVICES}, extra skipped`);
  }
  return targets.slice(0, MAXIMUM_CHECKED_SERVICES);
}

/** 스냅샷 설정 > 대상 병렬 점검 > {service_id: {is_ok, is_slow, status_code, latency_milliseconds, error}} */
export async function runChecks(config, fetchImpl, clock = Date.now) {
  const slowMilliseconds = toPositiveNumber(config?.alert?.slow_milliseconds, DEFAULT_SLOW_MILLISECONDS);
  const targets = selectCheckTargets(config?.services);
  const results = await Promise.all(
    targets.map((service) => checkService(service, slowMilliseconds, fetchImpl, clock)),
  );
  return Object.fromEntries(targets.map((service, index) => [service.id, results[index]]));
}

/** 점검 1회: 호출 > 지연 시간 측정 > 본문 취소 > 정상·slow 판정 (예외는 라벨로 변환) */
async function checkService(service, slowMilliseconds, fetchImpl, clock) {
  const { url, expect } = service.external;
  const timeoutSeconds = toPositiveNumber(service.external.timeout_seconds, DEFAULT_TIMEOUT_SECONDS);
  const startedMilliseconds = clock();
  let response;
  try {
    response = await fetchImpl(url, {
      method: 'GET',
      redirect: 'manual',
      signal: AbortSignal.timeout(timeoutSeconds * MILLISECONDS_PER_SECOND),
      headers: { 'user-agent': USER_AGENT },
    });
  } catch (error) {
    const errorLabel = classifyError(error);
    console.log(`[control-tower worker check] failed : service ${service.id} label ${errorLabel}`);
    return buildFailure(errorLabel, clock() - startedMilliseconds);
  }
  const latencyMilliseconds = clock() - startedMilliseconds;
  cancelBody(response);
  const isOk = isStatusOk(response.status, expect);
  return {
    is_ok: isOk,
    is_slow: isOk && latencyMilliseconds > slowMilliseconds,
    status_code: response.status,
    latency_milliseconds: latencyMilliseconds,
    error: null,
  };
}

/** 예외 > 라벨 (순서: timeout > tls_error > connection_error > error) */
export function classifyError(error) {
  if (TIMEOUT_ERROR_NAMES.has(error?.name)) return ERROR_LABEL_TIMEOUT;
  if (TLS_ERROR_PATTERN.test(String(error?.message ?? ''))) return ERROR_LABEL_TLS;
  if (error instanceof TypeError) return ERROR_LABEL_CONNECTION;
  return ERROR_LABEL_UNKNOWN;
}

function buildFailure(errorLabel, latencyMilliseconds) {
  return { is_ok: false, is_slow: false, status_code: null, latency_milliseconds: latencyMilliseconds, error: errorLabel };
}

/** 문자열 단순 비교 (로캘 무관, Python sorted와 같은 순서) */
function compareCodePoints(left, right) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function toPositiveNumber(value, fallback) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback;
}
