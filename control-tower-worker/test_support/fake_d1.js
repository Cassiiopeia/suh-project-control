/**
 * 테스트용 D1 가짜: node:sqlite 메모리 DB + 실제 마이그레이션 SQL, D1 API 모양(prepare > bind > first/all/run, batch)만 흉내
 * test/ 밖에 두는 이유: node --test 기본 패턴(test 폴더 하위 전부)에 잡히지 않게
 */
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

const MIGRATION_PATH = new URL('../migrations/0001_init.sql', import.meta.url);

class FakeD1PreparedStatement {
  constructor(database, sql, parameters = []) {
    this.database = database;
    this.sql = sql;
    this.parameters = parameters;
  }

  bind(...parameters) {
    // D1은 undefined 바인딩을 거부
    if (parameters.some((parameter) => parameter === undefined)) {
      throw new TypeError('D1_TYPE_ERROR: undefined bind value');
    }
    return new FakeD1PreparedStatement(this.database, this.sql, parameters);
  }

  async first() {
    const row = this.database.prepare(this.sql).get(...this.parameters);
    return row === undefined ? null : { ...row };
  }

  async all() {
    const rows = this.database.prepare(this.sql).all(...this.parameters);
    return { success: true, results: rows.map((row) => ({ ...row })), meta: {} };
  }

  async run() {
    return this.runSync();
  }

  runSync() {
    const outcome = this.database.prepare(this.sql).run(...this.parameters);
    return { success: true, results: [], meta: { changes: Number(outcome.changes) } };
  }
}

export class FakeD1Database {
  constructor() {
    this.database = new DatabaseSync(':memory:');
    this.database.exec(readFileSync(MIGRATION_PATH, 'utf8'));
    this.batchCallCount = 0;
  }

  prepare(sql) {
    return new FakeD1PreparedStatement(this.database, sql);
  }

  /** 묶음 실행: D1처럼 트랜잭션 (하나라도 실패하면 전부 되돌림) */
  async batch(statements) {
    this.batchCallCount += 1;
    this.database.exec('BEGIN');
    try {
      const outcomes = statements.map((statement) => statement.runSync());
      this.database.exec('COMMIT');
      return outcomes;
    } catch (error) {
      this.database.exec('ROLLBACK');
      throw error;
    }
  }

  /** 테스트 확인용 직접 조회 */
  query(sql, ...parameters) {
    return this.database.prepare(sql).all(...parameters).map((row) => ({ ...row }));
  }

  metaValue(key) {
    const row = this.database.prepare('SELECT value FROM meta WHERE key = ?').get(key);
    return row === undefined ? null : row.value;
  }

  setMetaValue(key, value) {
    this.database.prepare('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)').run(key, value);
  }
}
