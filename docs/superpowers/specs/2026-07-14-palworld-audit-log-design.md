# suh-ai-server 감사로그(Audit Log) — PostgreSQL 기록

- 날짜: 2026-07-14
- 상태: 사용자 승인 대기
- 관련: `docs/superpowers/specs/2026-07-14-palworld-admin-overhaul-design.md` (어드민 개편, #53)

## 1. 배경 / 목표

팰월드 관리자 페이지는 카톡방에 공유된 단일 API Key로 누구나 서버 제어(시작/중지/재시작)와
설정 수정이 가능하다. **누가(어느 IP가) 언제 무엇을 바꿨는지** 기록이 없어, 설정이 바뀌거나
서버가 재시작돼도 추적할 수 없다. 관리 행위를 PostgreSQL에 감사로그로 기록하고 관리자
페이지에서 조회할 수 있게 한다.

## 2. 확정된 요구사항 (브레인스토밍 결과)

- **기록 대상**: 서버 제어(시작/중지/재시작), 설정 수정(변경 diff 포함), 백업 생성
- **행위자 식별**: 클라이언트 IP만 (`X-Forwarded-For` 첫 값 → 없으면 `remote_addr`)
- **저장소**: PostgreSQL `suh_ai_server` DB (기구축: `suh-project.synology.me:5430`, DB는 사용자가 생성 완료)
- **확장성**: 카테고리(enum) 2단 구조 — 팰월드 외 서비스(OCR/Vision/시스템)도 같은 테이블 사용 가능
- **enum 방식**: Python 코드 enum + DB는 VARCHAR (Spring `@Enumerated(EnumType.STRING)` 철학 —
  PG native ENUM은 값 변경 시 ALTER TYPE 필요라 배제)
- **마이그레이션**: `yoyo-migrations` (순수 SQL 파일 + 이력 테이블, Flyway와 동일 개념, pip 설치)
- **접속정보**: `flask/.env` (gitignore) + GitHub Secret `FLASK_ENV_FILE` 통째 주입 (CICD가 서버에 파일 생성)
- **Fail-open**: DB 다운 시 감사 기록만 스킵(warning 로그), 관리 행위 자체는 정상 처리
- **Redis**: 감사로그에 불필요 — 범위 제외

## 3. DB 설계

### 마이그레이션 `flask/migrations/0001__create_audit_log.sql`

```sql
CREATE TABLE audit_log (
    id           BIGSERIAL    PRIMARY KEY,
    occurred_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    category     VARCHAR(32)  NOT NULL,
    action       VARCHAR(64)  NOT NULL,
    actor_ip     VARCHAR(64)  NOT NULL,
    detail       JSONB        NULL
);

COMMENT ON TABLE audit_log IS 'suh-ai-server 관리 행위 감사 로그';
COMMENT ON COLUMN audit_log.category IS '서비스 카테고리 (코드 enum: PALWORLD, SYSTEM, ...)';
COMMENT ON COLUMN audit_log.action IS '행위 (코드 enum: SERVER_START, SETTINGS_UPDATE, ...)';
COMMENT ON COLUMN audit_log.detail IS '액션별 부가정보 (설정 변경 diff 등)';

CREATE INDEX idx_audit_log_category_occurred_at
    ON audit_log (category, occurred_at DESC);
```

- 적용 이력은 yoyo가 `_yoyo_migration` 테이블로 자체 관리 (Flyway의 `flyway_schema_history` 상당)
- 마이그레이션은 **앱 기동 시 자동 적용** (`run.py`에서 yoyo apply — Spring Boot + Flyway와 동일한 경험)
- DB 연결 실패 시 마이그레이션 스킵 + warning, 앱은 정상 기동

### 코드 enum (`service/audit_service.py`)

```python
class AuditCategory(str, Enum):
    PALWORLD = "PALWORLD"
    SYSTEM = "SYSTEM"        # 향후 확장용 예약

class AuditAction(str, Enum):
    SERVER_START = "SERVER_START"
    SERVER_STOP = "SERVER_STOP"
    SERVER_RESTART = "SERVER_RESTART"
    SETTINGS_UPDATE = "SETTINGS_UPDATE"
    BACKUP_CREATE = "BACKUP_CREATE"
```

새 카테고리/액션 추가 = 코드 enum 한 줄 (DB 마이그레이션 불필요).

## 4. 아키텍처

### 4.1 감사 서비스 (`service/audit_service.py` — 신규)

- `record(category: AuditCategory, action: AuditAction, actor_ip: str, detail: dict | None) -> bool`
  - psycopg2로 동기 INSERT (관리 행위는 하루 수 건 수준 — 큐/배치 불필요)
  - 커넥션은 호출 시 획득·반납 (`psycopg2` 단순 연결; 빈도가 낮아 풀 불필요)
  - **예외는 전부 삼키고 warning 로그** — 감사 실패가 관리 행위를 막지 않는다 (fail-open)
- `list_logs(lines: int) -> dict` — 최근 N건 조회(현재 카테고리가 하나라 필터 없음 — 필요 시 추가), 로그 뷰어 응답 형태로 반환:
  `{"source": "audit", "exists": bool(DB 연결 성공), "log_file": "postgresql://…/suh_ai_server(마스킹)", "size_bytes": 0, "logs": [문자열...]}`
  - 각 로그 라인은 백엔드에서 포맷: `[2026-07-14T15:42:45+09:00] 192.168.0.10 · SERVER_RESTART`
    / 설정 변경은 `... · SETTINGS_UPDATE (ExpRate: 2.0 → 3.0, DeathPenalty: All → Item)`
  - DB 연결 실패 시 `exists: false` — 기존 뷰어가 "로그 파일이 아직 없습니다: (경로)" 패턴으로 안내

### 4.2 DB 설정 (`config/db_config.py` — 신규)

- `python-dotenv`로 `flask/.env` 로드 (파일 없으면 무시 — 로컬 테스트/CI에서도 기동)
- `AUDIT_DATABASE_URL` 환경변수 1개: `postgresql://user:pass@host:5430/suh_ai_server`
- URL 미설정 시 감사 기능 전체 비활성(기록 스킵 + 조회는 `exists:false`) — 서버 없는 환경 대비

### 4.3 라우터 연동 (`router/palworld_router.py` 수정)

- `_client_ip()` 헬퍼: `X-Forwarded-For` 첫 값 → `remote_addr`
- 기록 지점 (성공 시에만 기록):
  - `POST /palworld/start|stop|restart` → `SERVER_START|STOP|RESTART`
  - `PUT /palworld/settings` → `SETTINGS_UPDATE`, detail = `{"changed": {키: {"from": 이전값, "to": 새값}}}`
    (변경 전 ini를 읽어 diff 계산 — 실제로 달라진 키만 기록, 변경 0건이면 기록 생략)
  - `POST /palworld/backups` → `BACKUP_CREATE`, detail = `{"name": 백업명}`
- `GET /palworld/logs?source=audit` → 파일 tail 대신 `audit_service.list_logs()` 분기
- Swagger: logs source enum에 `audit` 추가

### 4.4 프론트 (`static/js/palworld.js` 수정)

- 로그 뷰어 소스 목록에 `{id: 'audit', label: '감사'}` 추가 — 끝. (응답 형태가 기존과 동일하므로
  뷰어/포맷 변경 없음)

### 4.5 시크릿/배포

- `flask/.env` (로컬 생성, **커밋 금지**):
  ```
  AUDIT_DATABASE_URL=postgresql://<user>:<password>@suh-project.synology.me:5430/suh_ai_server
  ```
- `.gitignore`에 `suh-ai-server/flask/.env` 추가
- GitHub Secret `FLASK_ENV_FILE`: .env 내용 통째 (API로 등록 — 웹/로그 노출 없음)
- `SUH-AI-PROJECT-CONTROL.yaml`: Flask 재시작 job의 deploy-flask.ps1 실행 **전에** SSH 스텝 추가 —
  Secret 내용을 `C:\AI\suh-ai-server\flask\.env`로 기록 (Secret 미등록 시 스킵, 기존 파일 유지)
- `requirements.txt`: `psycopg2-binary`, `yoyo-migrations`, `python-dotenv` 추가
  (deploy-flask.ps1의 기존 `pip install -r requirements.txt` 스텝이 자동 설치)

## 5. 에러 처리

| 상황 | 동작 |
|------|------|
| DB 다운/URL 미설정 상태에서 관리 행위 | 행위는 정상 처리, 감사 기록만 스킵 + warning 로그 |
| DB 다운 상태에서 감사 탭 조회 | `exists: false` + 마스킹된 DB 위치 안내 (500 아님) |
| 앱 기동 시 DB 다운 | 마이그레이션 스킵 + warning, 앱 정상 기동 (다음 기동 시 재시도) |
| detail 직렬화 실패 | fail-open과 동일 — 기록 스킵 + warning |
| 관리 행위 자체가 실패 (예: start 실패) | 감사 기록하지 않음 (성공한 행위만 기록) |

## 6. 테스트

- `audit_service.record`: 성공 INSERT(mock cursor), DB 예외 시 False 반환 + 행위 비차단(fail-open)
- settings diff 계산: 변경 키만 추출, 변경 0건 시 기록 생략
- `_client_ip`: XFF 첫 값 / XFF 없음 → remote_addr
- 라우터: start 성공 시 record 호출됨(mock), start 실패 시 record 미호출, `source=audit` 분기 응답 형태
- 마이그레이션 SQL: yoyo 파싱 가능성 (문법 검증)
- 기존 49개 테스트 회귀 없음

## 7. 범위 제외 (YAGNI)

- 사용자 계정/닉네임 식별 (IP만 — 사용자 결정)
- Redis 연동
- 감사로그 보존기간/파티셔닝 (개인 서버 규모에서 불필요)
- 조회 전용 별도 페이지 (로그 탭 소스로 충분)
- 실패한 행위 기록 (성공만 기록)

## 8. 배포 체크리스트

1. GitHub Secret `FLASK_ENV_FILE` 등록 (구현 단계에서 API로 처리)
2. main 머지 → 워크플로우가 .env 생성 + pip install + Flask 재시작 → 기동 시 yoyo가 `audit_log` 테이블 자동 생성
3. 확인: 서버 재시작 한 번 → 감사 탭에 `SERVER_RESTART` 기록 노출
