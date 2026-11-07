/**
 * 1분 크론: 외부 점검·기록 > 심박 감시 > (매시 정각) 7일 지난 check_run 삭제
 * 단계별 독립 실행 (한 단계 실패가 다음 단계를 막지 않음), 설정이 없으면 심박 감시만
 */
import { runChecks } from './checks.js';
import { watchHeartbeat } from './emergency.js';
import { buildPublicRollup, calculateFirstStatusDay } from './public_rollup.js';
import { advanceTodayRollup, appendRecentResults, calculateRecentResultLimit } from './rollups.js';
import {
  MetaKey, buildCheckRunInsertStatement, buildDailyRollupUpsertStatement, buildMetaUpsertStatement,
  deleteCheckRunsBefore, getDailyRollupsSince, getMetaValues, parseJsonObject,
} from './store.js';
import { toIsoUtc, toKstDay } from './time.js';

// check_run 보관 기간 (밀리초, 7일)
const CHECK_RUN_RETENTION_MILLISECONDS = 7 * 24 * 60 * 60 * 1000;
// 정리 실행 시점: 매시 이 분(UTC)에만
const CLEANUP_MINUTE = 0;

/** 크론 1회: 점검 기록 > 심박 감시 > 정리 */
export async function runScheduled(environment, nowMilliseconds, fetchImpl) {
  await runStep('checks', () => recordExternalChecks(environment.DB, nowMilliseconds, fetchImpl));
  await runStep('watchdog', () => watchHeartbeat(environment, nowMilliseconds, fetchImpl));
  if (new Date(nowMilliseconds).getUTCMinutes() === CLEANUP_MINUTE) {
    await runStep('cleanup', () => deleteOldCheckRuns(environment.DB, nowMilliseconds));
  }
}

/** 단계 실행: 예외는 이름만 기록하고 삼킴 */
async function runStep(stepName, step) {
  try {
    await step();
  } catch (error) {
    console.error(`[control-tower worker cron] ${stepName} failed : ${error?.name ?? 'unknown'}`);
  }
}

/**
 * 외부 점검 > batch 1회 기록 (check_run 1행, 최근 결과, 오늘 집계, 날짜 바뀌면 전날 daily_rollup + last_rollup_day)
 * 전날 마감 또는 공개 집계 없음 > daily_rollup 90일 1회 읽어 public_rollup_json도 같은 batch에
 * 설정 없음·점검 대상 없음 > 기록 생략
 */
async function recordExternalChecks(database, nowMilliseconds, fetchImpl) {
  const meta = await getMetaValues(database, [
    MetaKey.CONFIG_JSON, MetaKey.RECENT_RESULTS_JSON, MetaKey.TODAY_ROLLUP_JSON, MetaKey.LAST_ROLLUP_DAY,
    MetaKey.PUBLIC_ROLLUP_JSON,
  ]);
  const config = parseJsonObject(meta[MetaKey.CONFIG_JSON]);
  if (config === null) return;
  const results = await runChecks(config, fetchImpl);
  if (Object.keys(results).length === 0) return;

  const checkedAt = toIsoUtc(nowMilliseconds);
  const recentResults = appendRecentResults(
    parseJsonObject(meta[MetaKey.RECENT_RESULTS_JSON]), results, checkedAt, calculateRecentResultLimit(config),
  );
  const today = toKstDay(nowMilliseconds);
  const { todayRollup, finishedRollup } = advanceTodayRollup(parseJsonObject(meta[MetaKey.TODAY_ROLLUP_JSON]), results, today);
  const statements = [
    buildCheckRunInsertStatement(database, checkedAt, results),
    buildMetaUpsertStatement(database, MetaKey.RECENT_RESULTS_JSON, JSON.stringify(recentResults)),
    buildMetaUpsertStatement(database, MetaKey.TODAY_ROLLUP_JSON, JSON.stringify(todayRollup)),
  ];
  // 전날 마감: 같은 날짜를 이미 기록했으면 생략
  const shouldWriteFinishedRollup = finishedRollup !== null && finishedRollup.day !== meta[MetaKey.LAST_ROLLUP_DAY];
  if (shouldWriteFinishedRollup) {
    statements.push(...buildFinishedRollupStatements(database, finishedRollup));
    console.log(`[control-tower worker cron] daily rollup written : day ${finishedRollup.day}`);
  }
  // 공개 집계: 하루 1회 (첫 배포 등 값이 없으면 생길 때까지)
  if (shouldWriteFinishedRollup || meta[MetaKey.PUBLIC_ROLLUP_JSON] === null) {
    const writtenFinishedRollup = shouldWriteFinishedRollup ? finishedRollup : null;
    const publicRollup = await rebuildPublicRollup(database, config, writtenFinishedRollup, nowMilliseconds);
    statements.push(buildMetaUpsertStatement(database, MetaKey.PUBLIC_ROLLUP_JSON, JSON.stringify(publicRollup)));
  }
  await database.batch(statements);
}

/** daily_rollup 첫 막대 날짜부터 1회 읽기 + 방금 마감한 날 > 공개 서비스 집계 (오늘 제외) */
async function rebuildPublicRollup(database, config, finishedRollup, nowMilliseconds) {
  const firstDay = calculateFirstStatusDay(nowMilliseconds);
  const rollupRows = await getDailyRollupsSince(database, firstDay);
  return buildPublicRollup(config, rollupRows, finishedRollup, firstDay, toKstDay(nowMilliseconds));
}

/** 마감 집계 > daily_rollup upsert 행들 + last_rollup_day */
function buildFinishedRollupStatements(database, finishedRollup) {
  const rollupStatements = Object.entries(finishedRollup.services).map(([serviceId, [total, okCount]]) =>
    buildDailyRollupUpsertStatement(database, finishedRollup.day, serviceId, total, okCount));
  return [...rollupStatements, buildMetaUpsertStatement(database, MetaKey.LAST_ROLLUP_DAY, finishedRollup.day)];
}

async function deleteOldCheckRuns(database, nowMilliseconds) {
  const deletedCount = await deleteCheckRunsBefore(database, toIsoUtc(nowMilliseconds - CHECK_RUN_RETENTION_MILLISECONDS));
  if (deletedCount > 0) console.log(`[control-tower worker cron] old check runs deleted : ${deletedCount}`);
}
