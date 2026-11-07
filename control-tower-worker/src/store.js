/**
 * D1 접근 공통: meta 키값 읽기·묶음 쓰기, check_run 기록·최신 1행·정리, daily_rollup 기록
 * 여러 행 쓰기는 batch 1회 (D1 batch = 트랜잭션)
 */

// meta 키 (값은 전부 문자열)
export const MetaKey = Object.freeze({
  LAST_HEARTBEAT_AT: 'last_heartbeat_at', // 마지막 심박 수신 (ISO UTC)
  EMERGENCY_STATE: 'emergency_state', // ok | down
  EMERGENCY_SINCE: 'emergency_since', // 끊김 시작 = down 전환 당시 마지막 심박 (ISO UTC)
  CONFIG_JSON: 'config_json', // Flask 스냅샷 JSON
  CONFIG_VERSION: 'config_version', // 스냅샷 버전 (Registry.version())
  PUBLIC_INCIDENTS_JSON: 'public_incidents_json', // 공개 장애 목록 JSON
  LAST_ROLLUP_DAY: 'last_rollup_day', // daily_rollup에 마지막으로 기록한 KST 날짜
  TODAY_ROLLUP_JSON: 'today_rollup_json', // {"day": KST, "services": {id: [total, ok]}}
  RECENT_RESULTS_JSON: 'recent_results_json', // {id: [{is_ok, is_slow, checked_at}, ...]} 최신순
});

const UPSERT_META_SQL = 'INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value';
const UPSERT_DAILY_ROLLUP_SQL = 'INSERT INTO daily_rollup (day, service_id, total, ok) VALUES (?, ?, ?, ?) '
  + 'ON CONFLICT (day, service_id) DO UPDATE SET total = excluded.total, ok = excluded.ok';

/** meta 여러 키 1회 조회 > {key: value | null} */
export async function getMetaValues(database, keys) {
  const placeholders = keys.map(() => '?').join(', ');
  const { results } = await database.prepare(`SELECT key, value FROM meta WHERE key IN (${placeholders})`)
    .bind(...keys).all();
  const valueByKey = Object.fromEntries(keys.map((key) => [key, null]));
  for (const row of results) valueByKey[row.key] = row.value;
  return valueByKey;
}

export function buildMetaUpsertStatement(database, key, value) {
  return database.prepare(UPSERT_META_SQL).bind(key, String(value));
}

/** meta 여러 키 묶음 저장 (비어 있으면 생략) */
export async function setMetaValues(database, valueByKey) {
  const statements = Object.entries(valueByKey)
    .map(([key, value]) => buildMetaUpsertStatement(database, key, value));
  if (statements.length > 0) await database.batch(statements);
}

export function buildCheckRunInsertStatement(database, checkedAt, results) {
  return database.prepare('INSERT INTO check_run (checked_at, results_json) VALUES (?, ?)')
    .bind(checkedAt, JSON.stringify(results));
}

export function buildDailyRollupUpsertStatement(database, day, serviceId, total, okCount) {
  return database.prepare(UPSERT_DAILY_ROLLUP_SQL).bind(day, serviceId, total, okCount);
}

/** 최신 check_run 1행 > {checked_at, results} | null (results 손상 시 빈 객체) */
export async function getLatestCheckRun(database) {
  const row = await database.prepare('SELECT checked_at, results_json FROM check_run ORDER BY id DESC LIMIT 1').first();
  if (row === null) return null;
  const results = parseJsonObject(row.results_json);
  return { checked_at: row.checked_at, results: results ?? {} };
}

/** 기준 시각(ISO UTC) 이전 check_run 삭제 > 삭제 행 수 */
export async function deleteCheckRunsBefore(database, cutoffIso) {
  const outcome = await database.prepare('DELETE FROM check_run WHERE checked_at < ?').bind(cutoffIso).run();
  return outcome?.meta?.changes ?? 0;
}

/** 저장된 스냅샷 설정 > 객체 | null (없거나 손상) */
export async function loadConfig(database) {
  const { [MetaKey.CONFIG_JSON]: configJson } = await getMetaValues(database, [MetaKey.CONFIG_JSON]);
  return parseJsonObject(configJson);
}

/** JSON 문자열 > 일반 객체 (배열·손상·null이면 null) */
export function parseJsonObject(text) {
  if (typeof text !== 'string') return null;
  try {
    const value = JSON.parse(text);
    return isPlainObject(value) ? value : null;
  } catch {
    return null;
  }
}

export function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
