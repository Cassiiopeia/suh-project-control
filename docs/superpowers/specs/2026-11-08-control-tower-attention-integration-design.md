# 관제소 확인할 일(attention) 연동 설계 (#174)

## 1. 의도

- 운영 앱(elum, passQL, 이후 추가 앱)은 각자 관리자 화면에 "확인할 일"을 가진다: 새 의견, 처리 안 된 신고, 검토 대기, AI 이상, 비용 상한, 멈춘 작업 등.
- 지금은 앱마다 관리자 화면에 들어가야만 처리할 게 있는지 안다. 관제소는 서비스 생존만 본다.
- 목표: **앱이 무엇이든 같은 규격 하나로** 확인할 일을 관제소에 모으고, 대시보드와 디스코드로 알리고, 처리 화면으로 바로 보낸다.
- 사용자 요구: "한번 구축하면 나중에 바꾸기 힘들다. 최대한 확장성 있게 다 생각해 놓고 구현." → 규격(앱과의 계약)은 처음부터 넓게 잡고, 관제소 쪽 동작은 관리자 화면 설정으로 바꿀 수 있게 한다.

## 2. 목표 / 비목표 / 반목표

목표
- 앱 ↔ 관제소 계약 `attention v1` 확정 (JSON Schema 단일 원본 + 가이드 문서 + 참조 구현)
- 가져오기(pull) 방식 구현, 보내기(push) 방식도 같은 형식으로 구현
- 항목 종류 3가지(count, gauge, state)와 미지 종류의 안전한 표시
- 관제소 관리자 화면에서 앱 재배포 없이 항목별 표시, 이름, 수준, 알림 규칙, 알림 채널을 덮어쓰기
- 대시보드 카드, 디스코드 알림, 일일 요약 포함, 변경 이력 저장
- 연동 소스 자체의 상태(정상, 인증 실패, 규격 위반, 시간 초과, 오래됨) 감시

비목표 (v1에서 하지 않음, 규격에 자리만 둠)
- 관제소에서 앱 데이터 쓰기(상태 변경, 답장)
- 항목의 개별 건 목록이나 본문 전달 (개인정보를 관제소로 옮기지 않음)
- 시계열 그래프 화면 (#149 Prometheus/Grafana 영역, 이력 데이터는 쌓아 둠)
- 공개 status 페이지 노출

반목표 (이렇게 되면 실패)
- 항목 하나 추가할 때마다 관제소 코드를 고쳐야 함
- 같은 일을 관제소와 앱 두 곳에서 처리해 상태가 어긋남
- 앱 하나가 느리거나 이상한 응답을 줘서 관제소 감시 틱 전체가 밀림
- 앱 버전이 섞여 있을 때(구버전 앱, 신버전 관제소 또는 반대) 깨짐
- 알림 폭주 (같은 내용 반복, 재배포 직후 몰아치기)

## 3. 계약: attention v1

### 3.1 전달 방식 2가지 (같은 본문)

| 방식 | 요청 | 용도 |
|---|---|---|
| 가져오기 (pull, 기본) | 관제소 → `GET {source.url}` | 주기 수집. 관제소가 재배포돼도 다음 수집에서 그대로 복구 |
| 보내기 (push, 선택) | 앱 → `POST /control/attention/{project_id}/{source_id}` | 즉시 알리고 싶은 변화. 본문은 pull 응답과 동일한 "스냅샷" |

- 두 방식 모두 **스냅샷 교체** 의미: 본문은 그 소스의 현재 항목 전체. 증분(이벤트) 아님. 그래서 순서가 뒤바뀌거나 한 번 빠져도 다음 스냅샷이 바로잡는다.
- 늦게 도착한 스냅샷(`generated_at`이 이미 반영한 값보다 이전)은 버린다.

### 3.2 인증

- pull: 관제소가 `X-Control-Token: {CONTROL_PULL_TOKEN_<PROJECT>__<SOURCE>}` 헤더로 요청 (프로젝트와 소스 사이 구분자는 밑줄 2개). 앱은 상수 시간 비교로 검증.
- push: 앱이 `X-Control-Token: {CONTROL_EVENT_TOKEN_<PROJECT>}` (기존 이벤트 입구와 같은 토큰).
- 방향별 토큰 분리: 한쪽 유출이 양방향 위조로 이어지지 않게.
- 토큰 교체: 앱과 관제소 모두 "현재 + 이전" 2개를 허용(`..._PREVIOUS` 환경변수)해서 무중단 교체. 기존 `/control/events` 입구도 같은 `_PREVIOUS` 규칙을 지원하도록 함께 바꿈 (같은 토큰을 쓰는 두 입구의 동작 일치). [내 결정]
- 토큰 이름의 `<PROJECT>`, `<SOURCE>`는 id를 대문자로, `-`는 `_`로 바꾼 값 (기존 이벤트 토큰 규칙과 같음).
- `source_id` 규칙: `^[a-z][a-z0-9]*$`, 20자 이하 (`-`, `_` 금지 → `__` 구분자와 합쳐 환경변수 이름 충돌 불가). [내 결정]
- push 전용 소스는 변화가 없어도 최소 5분마다 스냅샷을 보낸다 (관제소의 끊김 판정 기준). [내 결정]

### 3.3 본문

```json
{
  "schema": "attention",
  "version": "1.0",
  "source": {
    "app": "elum-server",
    "app_version": "2.3.1",
    "environment": "production",
    "admin_base_url": "https://elum.example/admin"
  },
  "generated_at": "2026-11-08T12:00:00Z",
  "poll_after_seconds": 60,
  "items": [
    {
      "key": "feedback.new",
      "label": "새 의견",
      "kind": "count",
      "count": 3,
      "total": 182,
      "level": "info",
      "group": "사용자",
      "description": "보호자가 앱에서 보낸 처리 전 의견",
      "admin_url": "https://elum.example/admin/feedbacks?status=NEW",
      "latest_at": "2026-11-08T11:58:00Z",
      "detail": "가장 오래된 건 2일 전"
    },
    {
      "key": "budget.daily",
      "label": "오늘 AI 비용",
      "kind": "gauge",
      "value": 8.2,
      "limit": 10,
      "unit": "USD",
      "level": "warning",
      "admin_url": "https://elum.example/admin/ai/budget"
    },
    {
      "key": "ai.provider",
      "label": "AI 제공자 상태",
      "kind": "state",
      "state": "degraded",
      "level": "warning",
      "detail": "Gemini 응답 지연"
    }
  ]
}
```

### 3.4 필드 규칙

최상위

| 필드 | 필수 | 규칙 |
|---|---|---|
| `schema` | 예 | 고정 `"attention"` |
| `version` | 예 | `"주.부"`. 관제소는 주 버전이 아는 값(1)이면 받고, 부 버전은 무시 |
| `source.app` | 예 | 앱 식별 이름 (로그, 화면 표시용) |
| `source.app_version` | 아니오 | 앱 버전 |
| `source.environment` | 아니오 | `production`(기본) / `staging` / `development`. production 아니면 알림 안 함 |
| `source.admin_base_url` | 아니오 | 상대 `admin_url`의 기준 |
| `generated_at` | 예 | UTC ISO 8601. 순서 판단 기준 |
| `poll_after_seconds` | 아니오 | 다음 수집 희망 간격. 관제소는 [60, 3600]으로 자른 뒤 관리자 설정과 비교해 큰 값 사용 |
| `items` | 예 | 0~100개. 0개도 정상(확인할 일 없음) |

항목 공통

| 필드 | 필수 | 규칙 |
|---|---|---|
| `key` | 예 | `^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,3}$`, 64자 이하, 소스 안에서 유일. 관제소의 이력, 덮어쓰기, 알림 상태가 모두 이 key에 묶인다 → **한 번 정한 key는 바꾸지 않는다** |
| `label` | 예 | 1~40자. 화면, 디스코드에 그대로 표시 |
| `kind` | 예 | `count` / `gauge` / `state`. 모르는 kind는 label, detail, level만 표시하고 알림 규칙은 수준 상승만 적용 |
| `level` | 예 | `ok` / `info` / `warning` / `critical`. 앱이 판단한 심각도. 관제소 덮어쓰기로 바꿀 수 있음 |
| `group` | 아니오 | 화면 묶음 이름, 20자 이하 |
| `description` | 아니오 | 관리자 화면 설명, 200자 이하 |
| `admin_url` | 아니오 | 절대 https URL 또는 `/`로 시작하는 상대 경로(`admin_base_url` 기준). 그 외는 버림 |
| `latest_at` | 아니오 | 가장 최근 건 시각 |
| `detail` | 아니오 | 한 줄 보충, 80자 이하 |

kind별

| kind | 필드 | 의미 |
|---|---|---|
| `count` | `count` (필수, 0 이상 정수) | 지금 처리 안 된 개수 |
|  | `total` (선택, 0 이상 정수, 줄지 않음) | 지금까지 생긴 누적 개수. 있으면 "새로 생긴 건"을 정확히 셈(처리 1건 + 신규 1건이어도 감지) |
| `gauge` | `value` (필수, 숫자), `limit` (선택), `unit` (선택, 12자) | 현재 값과 상한 |
| `state` | `state` (필수, `ok` / `degraded` / `down` / `unknown`) | 상태값 |

- 모르는 필드는 무시한다 (앞으로 필드를 더해도 v1 유지).
- 의미를 바꾸거나 필드를 없앨 때만 주 버전을 올린다(v2). 관제소는 v1, v2를 함께 읽는다.
- **앱은 가능한 모든 항목을 항상 내보낸다(0이어도).** 관제소 관리자 화면이 이걸로 항목 목록을 알고, 무엇을 보여 줄지 관제소에서 고른다(단일 원본: 표시 설정은 관제소에만).

### 3.5 표준 key 목록 (권장 이름)

앱이 같은 뜻이면 같은 key를 쓴다. 목록 밖은 `custom.이름`.

| key | kind | 뜻 |
|---|---|---|
| `feedback.new` | count | 처리 전 의견 |
| `feedback.in_progress` | count | 확인 중 의견 |
| `report.unresolved` | count | 처리 안 된 신고 |
| `review.pending` | count | 검토 대기 콘텐츠 |
| `job.stuck` | count | 멈춘 예약, 작업 |
| `job.failed` | count | 실패한 작업 |
| `payment.failed` | count | 결제 실패 |
| `ai.alert` | count | AI 이상 제공자 수 |
| `ai.provider` | state | AI 제공자 상태 |
| `budget.daily` | gauge | 오늘 비용 |
| `queue.backlog` | gauge | 대기열 길이 |

### 3.6 응답 코드와 제한

| 상황 | 앱 응답 |
|---|---|
| 정상 | 200 + 본문 |
| 토큰 없음, 틀림 | 401 |
| 연동 꺼짐 | 404 |
| 일시 오류 | 503 (관제소는 실패로 기록, 마지막 값 유지) |

- 응답 5초 안, 본문 64KB 이하. 넘으면 관제소는 그 소스만 실패 처리.
- `ETag`를 주면 관제소는 `If-None-Match`로 요청하고 304면 변화 없음으로 처리 (선택).

## 4. 앱 쪽 (각 앱 레포)

- 엔드포인트 하나: `GET /control/attention` (경로는 앱이 정하고 관제소에 등록).
- 관리자 화면 "관제소 연동" 섹션:
  - 연동 켜기/끄기
  - 마지막 관제소 수집 시각, 토큰 설정 여부(값은 표시 안 함)
  - 현재 내보내는 항목 미리보기 (실제 응답과 같은 데이터)
- 항목 표시 여부, 이름, 수준 기준 같은 **관제소 표시 설정은 앱이 아니라 관제소에서** 한다. 앱은 사실(개수, 값, 상태)만 내보낸다.
- 개수 계산은 기존 관리자 대시보드 집계(elum `AdminDashboardAttention`, passQL `FeedbackService.countByStatus`)를 재사용.
- 참조 구현: 가이드 문서에 Spring 컨트롤러, 응답 record, 토큰 검사 필터 예시. 규격 검증은 JSON Schema 파일과 관제소 "연결 확인" 버튼으로.

## 5. 관제소 쪽 (이 레포, `suh-ai-server/flask`)

### 5.1 이름

- 기능 이름: **앱 확인할 일** (코드 `app_attention`). 기존 overview의 `needs_attention`(일시정지 서비스 수, 화면 "확인 필요")과 겹치지 않게 접두사 `app_`를 붙인다.
- 모듈 접두사 `service/control_tower/app_attention_*.py`.

### 5.2 연동 소스 (source)

- 한 프로젝트에 소스 여러 개 가능 (예: elum의 api 서버, 배치 서버). 식별: `(project_id, source_id)`.
- 등록은 **관제소 관리자 화면에서**(DB 저장). services.yml은 건드리지 않음 (`PROJECT_KEYS` 확장 불필요).
- 소스의 프로젝트는 관제소에 등록된 프로젝트만 허용 (services.yml + #159 관리 화면에서 추가한 프로젝트). 새 앱은 관리 화면에서 프로젝트를 추가하면 되므로 재배포 없음. 채널, 다운 억제는 기존 프로젝트 구조 그대로. [내 결정]
- 토큰 값은 DB에 두지 않고 환경변수(`CONTROL_PULL_TOKEN_<PROJECT>_<SOURCE>`, `_PREVIOUS`)만 사용. 화면에는 "설정됨 / 없음"만.
- 소스 설정 필드: `url`(https 또는 내부망 http, `${ENV}` 치환 허용), `is_enabled`, `mode`(`pull` / `push` / `both`), `interval_seconds`(기본 60, 60~3600, 폴러 틱이 60초라 그 아래는 의미 없음), `timeout_seconds`(기본 5, 1~10), `stale_after_seconds`(기본 interval×5).

### 5.3 수집 (pull) 과 받기 (push) 의 공통 처리

```
pull: 폴러 틱 > 수집할 때 된 소스만 > 병렬 GET (최대 8, 소스별 timeout) ─┐
push: POST /control/attention/<project>/<source> (요청 스레드) ───────────┤
                                                                          ▼
                    AppAttentionIngest.ingest(source, http 결과, now)   ← 하나의 처리 경로
                      1. 응답 분류 (ok / unauthorized / disabled / invalid / timeout / error / not_modified)
                      2. 본문 검증 (규격 위반 항목은 그 항목만 버리고 사유 기록, 최상위 위반은 소스 실패)
                      3. generated_at 이 반영한 값 이하면 버림
                      4. 소스별 잠금 + BEGIN IMMEDIATE 로 이전 상태 읽기 > 새 상태 쓰기 > 이력(바뀐 값만)
                      5. 알림 평가 (5.5) > 알림 계획 반환
                    > dispatcher.send (실패해도 상태 저장은 유지, 알림 평가 결과의 "보낸 시각"만 미반영 > 다음 수집에서 재평가)
```

- 폴러 단계는 새 파일 `poller_app_attention.py`의 `AppAttentionStep` (기존 `HeartbeatStep` 패턴). `tick()`의 저장 뒤, 초대 귀속 단계 옆에서 호출. 예외는 단계 안에서 삼키고 로그 (틱 보호).
- 수집 시점 판정: `마지막 시도 + interval - 5초 <= now` (틱 오차로 한 주기 밀리지 않게). 수집은 병렬이라 보통 소스 timeout(기본 5초) 안에 끝남. 틱당 전체 상한 10초, 넘으면 남은 소스는 다음 틱. [내 결정]
- HTTP: `requests.get(stream=True, allow_redirects=False)` + 64KB까지만 읽기, `check_runner.classify_error` 재사용. `ETag` 있으면 `If-None-Match`.
- push 입구: `POST /api/flask/control/attention/<project>/<source>`. nginx(`suh-ai-server/config/nginx.conf`)에 API 키 예외 경로를 하나 더 둔다(기존 `/control/events`와 같은 rate limit zone, 본문 64KB). `test_control_tower_nginx.py`의 "예외 경로는 정확히 1개" 검사는 "허용 목록과 정확히 일치"로 바꾼다.
- push 소스가 `mode=pull`이면 403 `push_disabled`.

### 5.4 저장 (SQLite, 기존 store mixin 패턴)

| 테이블 | 키 | 내용 |
|---|---|---|
| `app_attention_source` | project_id, source_id | 5.2 설정, created_at, updated_at |
| `app_attention_source_state` | project_id, source_id | last_attempt_at, last_success_at, last_result(5.3 분류), last_error, consecutive_failures, etag, last_generated_at, app, app_version, environment, is_baseline_done, failure_alerted_at |
| `app_attention_item` | project_id, source_id, key | kind, label, level, group, description, admin_url, latest_at, detail, count, total, value, limit, unit, state, raw_json(원본 항목, 미지 필드 보존), first_seen_at, updated_at, missing_since(스냅샷에서 빠진 시각) |
| `app_attention_item_override` | project_id, source_id, key | is_hidden, label, level_policy, alert_rule, threshold, channel_kind, mention_role (모두 null = 앱 값/기본 규칙) |
| `app_attention_item_alert` | project_id, source_id, key | last_alerted_at, last_alerted_total, last_alerted_count, last_alerted_level, is_threshold_exceeded |
| `app_attention_history` | id | project_id, source_id, key, observed_at, count, total, value, state, level (값이 바뀔 때만 1행) |

- 스냅샷에서 빠진 항목은 바로 지우지 않고 `missing_since`만 기록, 화면에서 숨김. 7일 지나면 삭제 (앱이 잠깐 항목을 빼는 배포 실수 보호).
- 이력 보관 90일, 기존 `purge()`에 추가. 이력은 v2 그래프·추세용으로 미리 쌓음.
- 기존 `store.py`(296줄)는 mixin 등록과 purge 한 줄만 추가. 나머지는 `app_attention_store.py`.

### 5.5 알림 규칙

항목별 **유효 설정** = 관제소 덮어쓰기 > kind별 기본값.

| 규칙(`alert_rule`) | 기본 적용 | 언제 알림 |
|---|---|---|
| `new` | count | 새로 생긴 건이 있을 때. `total` 있으면 total 증가분, 없으면 count 증가분 |
| `threshold` | gauge | value가 기준(덮어쓰기 `threshold` > 항목 `limit`) 이상으로 넘어갈 때 1번, 내려오면 해소 1번 |
| `state` | state | ok가 아닌 상태로 바뀔 때, ok로 돌아올 때 |
| `level` | 미지 kind | 유효 수준이 warning, critical로 올라갈 때 |
| `off` | — | 알림 없음 (대시보드만) |

공통 억제
- **기준선**: 소스의 첫 성공 수집은 저장만 하고 알림 없음 (등록 직후, DB 초기화 후 몰아치기 방지). 관제소 재배포는 DB가 남으므로 기준선 유지.
- **환경**: `environment`가 production이 아니면 알림 없음.
- **묶기**: 한 소스의 한 번 처리에서 나온 알림은 메시지 1건으로 묶음 (항목별 줄).
- **쿨다운**: 같은 항목 `new` 알림은 10분에 1번. 그 사이 늘어난 건 다음 알림에 합산 ("새 의견 +5, 지금 8건").
- **수준 → 채널**: 유효 수준 info, warning > 프로젝트 **`attention` 채널(#확인할일, 새 채널 종류)**. critical > 프로젝트 attention 채널 + `#관제-긴급`. ok > 알림 없음. 덮어쓰기 `channel_kind`로 status, error, report 선택 가능.
- **새 채널 종류 `attention`** (사용자 결정): `PROJECT_CHANNEL_KINDS`에 추가, 이름 `확인할일`, 공개 대상 `dev`(+관리자 항상). services.yml `discord.channel_visibility`에 `attention: [dev]` 추가.
  - 채널은 **연동 소스가 1개 이상 있는 프로젝트에만** 만든다 (확인할 일 없는 프로젝트 16개에 빈 채널이 생기지 않게). 디스코드 동기화 계획이 소스 유무를 보고 채널을 넣고 뺀다. 소스를 모두 지워도 채널은 지우지 않고 남김 (기존 동기화 원칙: 사람이 만든 기록 보존). [내 결정]
  - attention 채널 바인딩이 아직 없으면(동기화 전) 기존 대체 경로대로 `#관제-긴급`으로 감.
- **유효 수준**: `level_policy` = `app`(앱 값 사용, 기본) / 고정값(`info`/`warning`/`critical`) / `ok`(알림 안 하는 정보성).
- 디스코드 메시지: 제목 "elum 확인할 일", 줄마다 `label`, 증감, 현재값, `detail`. 링크는 첫 항목 `admin_url`, 항목별 링크는 본문 마크다운 링크.
- 기존 `Notification` 모델(scope, kind, severity, title, body, dedupe_key, link_url)과 `EventDispatcher` 채널 조회를 그대로 사용. kind는 채널 kind(기본 `attention`), dedupe_key = `attention:{project}:{source}:{tick 해시}`.

소스 자체 이상
- 연속 실패가 `stale_after_seconds`를 넘으면 프로젝트 `error` 채널에 "elum 확인할 일 연동 끊김 (사유)" 1번, 복구 시 1번.
- 같은 프로젝트의 서비스가 down이면 연동 끊김 알림은 생략 (서비스 다운 알림이 이미 나감, 기존 억제와 같은 원칙).
- 인증 실패(401)와 규격 위반은 바로 사유 표시, 알림은 같은 기준.

### 5.6 화면

관제소 페이지 (기존 탭 구조 유지)
- **현황 탭**: "앱 확인할 일" 섹션 추가. 프로젝트별 카드 > 그룹별 항목 줄 (label, 값, 수준 색, 마지막 갱신, 앱 관리자 바로가기). 0건이거나 ok인 항목은 접힌 "정상 n개"로.
- **관리 탭**: 프로젝트 행에 "앱 연동" 열기 > 소스 목록, 추가/수정/삭제, 토큰 설정 여부, 마지막 결과와 사유, "연결 확인"(즉시 1회 요청 > 검증 결과와 항목 미리보기만 반환. **상태, 기준선, 알림 상태는 바꾸지 않음** → 정식 수집 경로는 하나로 유지) [내 결정].
- 소스 상세의 항목 표: 항목마다 표시 여부, 이름, 수준 정책, 알림 규칙, 기준값, 채널. 앱이 보낸 원래 값은 회색으로 옆에 표시.
- **관리자 대시보드 카드**(`dashboard.html`): 관제소 카드 옆 "앱 확인할 일" 카드, warning 이상 개수 배지, 프로젝트별 한 줄 요약.
- 새 JS: `control-app-attention.js`(현황), `control-manage-app-attention.js`(관리). 기존 300줄 근접 파일(`control.js`, `control-manage.js`)에는 include와 호출 한 줄만.
- CSS는 미리 빌드된 Tailwind라 새 클래스가 필요하면 `frontend`에서 다시 빌드해 함께 커밋. 가능하면 기존 클래스만 사용.

### 5.7 관리 API (기존 manage API 규칙: 실패 400 `{"error":"invalid","fields":[...]}`, 변경은 감사 로그)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/control/app-attention` | 프로젝트별 유효 항목 (현황, 대시보드) |
| GET | `/control/app-attention/sources` | 소스 목록 + 상태 |
| POST | `/control/app-attention/sources` | 소스 추가 |
| PATCH / DELETE | `/control/app-attention/sources/<project>/<source>` | 수정, 삭제 (삭제 시 항목, 이력, 덮어쓰기 함께 삭제) |
| POST | `/control/app-attention/sources/<project>/<source>/test` | 연결 확인 (저장 안 함) |
| GET | `/control/app-attention/sources/<project>/<source>/items` | 항목 + 덮어쓰기 |
| PATCH | `/control/app-attention/items/<project>/<source>/<key>` | 항목 덮어쓰기 (null = 해제) |
| POST | `/control/attention/<project>/<source>` | push 입구 (API 키 예외, 프로젝트 토큰) |

- overview 응답에 `app_attention_summary` {open_item_count, warning_count, critical_count, failing_source_count} 추가.
- 일일 요약(digest)에 "앱 확인할 일" 섹션: 프로젝트별 열린 항목 수, 연동 끊긴 소스.

### 5.8 규격 단일 원본

- `docs/control-tower/attention/attention-v1.schema.json`: 계약 원본 (JSON Schema 2020-12).
- `docs/control-tower/attention/examples/*.json`: 유효, 무효 예시 모음.
- Flask 검증기 `app_attention_validation.py`는 의존성 추가 없이 직접 구현. 대신 테스트에서 `jsonschema`(개발 의존성)로 **스키마와 검증기가 모든 예시에 같은 판정을 내리는지** 확인 → 규격과 구현이 어긋나면 테스트 실패.
- `docs/control-tower/attention/README.md`: 앱 연동 가이드 (규격 요약, Spring 참조 구현, 토큰 등록, 연결 확인, 표준 key, 하지 말 것).

## 6. 각 앱 연동 (별도 이슈)

| 레포 | 내보낼 항목 (1차) |
|---|---|
| elum (Twin-Fang/elum) | `feedback.new`, `review.pending`, `job.stuck`, `ai.alert`, `budget.daily`, `report.unresolved` (기존 `AdminDashboardAttention`, `AdminSidebarBadges`) |
| passQL (Twin-Fang/passQL) | `feedback.new`, `feedback.in_progress` (`FeedbackService.countByStatus`) |

- 각 앱: 엔드포인트, 토큰 검사, 관리자 화면 "관제소 연동" 섹션.
- 관제소 #174 배포 후 연동 순서: 앱 배포 > 관제소에 토큰 env 등록 > 관리 화면에서 소스 추가 > 연결 확인 > 기준선 > 알림 시작.

## 7. 검증

- 단위: 검증기(스키마 일치), 알림 규칙(new/total, 쿨다운 합산, threshold 왕복, state, level, 기준선, 비production), 순서 뒤바뀜, 항목 누락 7일, 소스 실패/복구, 크기·시간 상한.
- 폴러 통합: 가짜 HTTP로 여러 틱, 틱 시간 상한.
- push: 토큰, mode, 404/403, 같은 처리 경로.
- 배포 후 실측: 가짜 소스(관제소 자체 테스트 엔드포인트 또는 카나리아)로 수집 > 알림 > 화면 확인, 캡처.

## 8. 빌더에게 맡기는 것

- 화면 세부 배치, 문구 다듬기, 색 (기존 관제소 화면 톤 유지)
- 내부 함수 분할, 파일 이름 세부 (300줄 규칙 지킴)
