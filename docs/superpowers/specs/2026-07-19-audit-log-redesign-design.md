# 감사로그 시스템 전면 개선 설계 (이슈 #104)

- 이슈: https://github.com/Cassiiopeia/suh-project-control/issues/104
- 대상: `suh-ai-server/flask` (Flask 관리자 서버)
- 날짜: 2026-07-19

## 배경 / 문제점

감사로그는 PostgreSQL `audit_log` 테이블에 기록되고, 팰월드 페이지의 텍스트 로그 뷰어 탭 하나로만 노출된다. 현재 문제:

1. **표시 정보 부족** — 화면에 category(PALWORLD/TTS)가 없어 `SERVER_START`가 어느 서비스인지 알 수 없다. TTS의 `{engine}` detail은 기록되지만 `_format_line()`이 `changed`/`name` 키만 읽어 화면에서 유실된다.
2. **IP 표기 혼란** — `actor_ip`에 X-Forwarded-For 체인 전체가 저장된다. 라우터마다 추출 로직이 다르다(팰월드: 첫 IP만, TTS: 체인 전체).
3. **감사 누락** — 모델 관리(`model_router`: 삭제/다운로드/취소)는 감사 기록이 전혀 없다. 실패한 제어 시도도 기록되지 않는다.
4. **수동 호출 구조** — 라우터마다 `audit_service.record()`를 직접 호출해야 해서 새 엔드포인트 추가 시 누락되기 쉽고, 이를 막는 문서/가드레일이 없다.
5. **전용 화면 부재** — 텍스트 라인 뷰어라 필터(카테고리/행위/기간)나 상세 보기(설정 diff 등)가 불가능하다.

## 설계

### 1) 공통 감사 기록 계층 — `@audited` 데코레이터

새 모듈 `util/audit_helper.py` (라우터 계층 유틸):

```python
@palworld_bp.route('/palworld/start', methods=['POST'])
@audited(AuditCategory.PALWORLD, AuditAction.SERVER_START)
def start():
    ...
```

동작 규약:

- **자동 수집**: `client_ip`(XFF 첫 항목, 없으면 remote_addr), `proxy_chain`(XFF 나머지 항목 리스트), `user_agent`(User-Agent 헤더).
- **성공/실패 자동 판정**: 핸들러 반환 응답의 status < 400 → `success=True`. status ≥ 400 또는 예외 발생 → `success=False`로 기록하고 detail에 `{'error': 메시지}` 병합. 예외는 기록 후 재발생(re-raise)시켜 기존 에러 흐름 유지.
- **GET 등 조회성 요청은 대상 아님** — 상태 변경 엔드포인트(POST/PUT/DELETE)에만 부착한다.
- **동적 detail**: 핸들러 내부에서 `set_audit_detail({'engine': engine_id})` 호출(flask.g 저장). 설정 diff처럼 계산되는 값도 이 방식.
- **동적 action**: `_control('start'|'stop'|...)`처럼 액션이 런타임에 정해지는 라우트는 `set_audit_action(AuditAction.X)` 헬퍼로 지정. 데코레이터에는 기본 action을 넘기고 g 값이 있으면 우선한다.
- **fail-open 유지**: 감사 기록 실패(DB 다운 등)는 관리 행위를 절대 막지 않는다 (기존 `audit_service` 정책 그대로).
- **요청 컨텍스트 밖**(백그라운드 스레드, 예: `palworld_updater`)은 기존 `audit_service.record()` 직접 호출 유지. actor는 `system`.

기존 수동 호출 이관:

| 위치 | 현재 | 변경 |
|---|---|---|
| `palworld_router._control` | 성공 시 record | `@audited` + `set_audit_action` |
| `palworld_router.put_settings` | diff 계산 후 record | `@audited` + `set_audit_detail(diff)` |
| `palworld_router.create_backup` | record | `@audited` |
| `tts_router.engine_control` | record | `@audited` + `set_audit_action`/`set_audit_detail` |
| `tts_router.add_voice` / `delete_voice` | record | `@audited` + `set_audit_detail` |
| `palworld_updater` (스레드) | record | 유지 (변경 없음) |

### 2) DB 마이그레이션 `0002__audit_log_actor_detail.sql`

```sql
ALTER TABLE audit_log
    ADD COLUMN client_ip   VARCHAR(64),
    ADD COLUMN proxy_chain JSONB,
    ADD COLUMN user_agent  TEXT,
    ADD COLUMN success     BOOLEAN NOT NULL DEFAULT true;

-- 백필: actor_ip 콤마 체인의 첫 항목 → client_ip, 나머지 → proxy_chain
```

- `actor_ip` 컬럼은 **삭제하지 않는다** (감사 원본 보존). 신규 기록도 호환을 위해 기존 형식 그대로 채운다.
- 백필은 SQL로 수행 (`split_part`, `string_to_array` 활용).
- 마이그레이션 적용 방식은 0001과 동일한 기존 절차를 따른다.

### 3) 감사 커버리지 보강

- `AuditCategory.MODEL` 신설 + `AuditAction`에 `MODEL_DELETE`, `MODEL_DOWNLOAD`, `MODEL_DOWNLOAD_CANCEL` 추가.
- `model_router`의 DELETE `/models/installed`, POST `/models/queue`, DELETE `/models/queue/<id>`에 `@audited` 부착. detail에 모델명/파일명 기록.
- category/action은 코드 enum + DB VARCHAR 구조라 **마이그레이션 불필요** (기존 정책 유지).

### 4) 조회 API — `GET /audit/logs`

새 블루프린트 `router/audit_router.py`:

- 쿼리 파라미터: `category`, `action`, `success`, `search`(detail/IP 부분 일치), `limit`(기본 100, 최대 500), `before_id`(키셋 페이징).
- 응답: `{'rows': [{id, occurred_at, category, action, client_ip, proxy_chain, user_agent, success, detail}], 'has_more': bool}`.
- `audit_service`에 구조화 조회 함수 `query_logs(...)` 추가. 기존 `list_logs()`(텍스트 라인)와 `palworld/logs?source=audit` 엔드포인트는 API 하위호환(Swagger/외부 호출)을 위해 유지하되, 카테고리 표시를 포함하도록 라인 포맷만 보정. (팰월드 페이지의 감사 탭 자체는 §5에서 제거)
- Swagger 문서 등록 (기존 라우터 패턴과 동일).

### 5) 전용 UI — 관리자 "감사로그" 페이지

- `admin_router`에 `/admin/audit` 페이지 라우트 추가, `templates/admin/audit.html` + `static/js/audit.js` 신설.
- `base.html` 왼쪽 네비에 "감사로그" 탭 추가 (shield 아이콘, "Flask 로그" 위).
- 테이블 컬럼:
  - **시간**: KST 변환, `MM-DD HH:mm:ss` 표시 (연도는 툴팁).
  - **카테고리**: 뱃지 (팰월드/TTS/모델/시스템, 색상 구분).
  - **행위**: 한국어 라벨 매핑은 `audit.js`에 상수로 보관. 예: `SERVER_START` → "팰월드 서버 시작", `TTS_START` + detail.engine → "TTS 엔진 시작 (supertonic)".
  - **실행 IP**: `client_ip`만 표시. `proxy_chain`/`user_agent`는 툴팁.
  - **결과**: 성공/실패 뱃지.
  - **상세**: detail 있으면 행 클릭으로 펼침 — 설정 diff는 key: from → to 표, 그 외는 JSON pretty.
- 필터 바: 카테고리 select, 행위 select(카테고리 연동), 성공/실패 select, 검색 input, 자동 새로고침(10초, 기존 뷰어와 동일 정책), 더 보기(키셋 페이징).
- 알 수 없는 action(라벨 매핑 없음)은 원문 코드 그대로 표시 — 새 enum 추가 시 UI가 깨지지 않게.
- `palworld.js`의 '감사' 탭은 제거하고, 로그 카드에 전용 페이지 링크 버튼 추가.

### 6) 에이전트 가드레일 (문서화)

- **`suh-ai-server/flask/CLAUDE.md` 신설**:
  - 규칙: "상태를 변경하는 관리 엔드포인트(POST/PUT/DELETE)를 추가하면 반드시 `@audited` 데코레이터를 부착한다."
  - `@audited` / `set_audit_detail` / `set_audit_action` 사용법 요약.
  - 새 action 추가 절차: `AuditAction` enum + `audit.js` 라벨 매핑만 추가 (마이그레이션 불필요).
  - 백그라운드 작업은 `audit_service.record()` 직접 호출.
- `audit_service.py`와 `audit_helper.py` 모듈 docstring에 동일 가이드 요약.

### 7) 테스트

- `test_audit_helper.py`: 데코레이터 성공/실패/예외 기록, IP 체인 분리, UA 수집, g 기반 detail/action 주입, fail-open.
- `test_audit_service.py` 확장: `query_logs` 필터/페이징, 신규 컬럼 기록.
- 라우터 테스트: 모델 관리 3종 감사 기록, 팰월드/TTS 이관 후 회귀 확인.
- 마이그레이션 백필 검증 (테스트 DB 또는 SQL 단위 검증).

## 비범위 (YAGNI)

- 사용자 계정/로그인 도입 (현재 Nginx 단일 API Key 구조 유지 — "누가"는 IP까지만).
- 감사로그 보존 기한/자동 삭제 정책.
- TTS 합성 요청(`POST /tts`) 자체의 감사 기록 (관리 행위가 아닌 일반 사용 API).

## 에러 처리

- 감사 DB 접근 실패: fail-open — 관리 행위는 정상 진행, warning 로그만.
- 조회 API에서 DB 실패: 기존 `list_logs`와 동일하게 빈 결과 + `exists:false` 성격의 응답 (UI는 "감사 DB에 연결할 수 없습니다" 표시).
- 데코레이터 내부 예외는 원래 요청 처리에 영향을 주지 않도록 격리.
