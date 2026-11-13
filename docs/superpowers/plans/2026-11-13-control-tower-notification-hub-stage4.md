# 관제소 알림 허브 4단계 구현 계획: Python·Java 서버용 클라이언트

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 다른 레포의 서버가 `init` 한 번, `notify` 한 줄로 관제소에 이벤트를 보낸다. 보내기 실패가 앱 요청을 막지 않는다.

**Architecture:** 이 레포 `clients/python`, `clients/java`에 둔다(규격과 같은 곳, 새 레포 없음). 두 클라이언트 모두 외부 의존성 없이 표준 라이브러리 HTTP만 쓴다. 필드 검증은 서버가 단일 원본이다. 클라이언트는 검증을 복사하지 않고, 테스트에서 클라이언트가 만든 본문을 `docs/control-tower/events/events-v1.schema.json`과 예시로 확인해 규격과 어긋나지 않게 묶는다.

**Tech Stack:** Python ≥3.9 (urllib, hatchling 빌드) / Java 17 (java.net.http, Gradle, JUnit 5)

**Spec:** `docs/superpowers/specs/2026-11-13-control-tower-notification-hub-design.md` (5.5, 6장 4단계), 규격 `docs/control-tower/events/README.md`

## Global Constraints

- 4단계 시작 전 확인 항목은 아래 [내 결정]으로 정하고 배포(게시)는 하지 않음 — PyPI·Maven Central 게시는 사용자 확인 후 별도 진행
  - Python 패키지 이름 `suh-control-tower` (import `suh_control_tower`), 버전 `0.1.0`, `requires-python >=3.9`, 의존성 0개 [내 결정]
  - Java 좌표 `kr.suhsaechan:suh-control-tower-client:0.1.0`, Java 17, 의존성 0개, Spring 자동 설정 없음(정적 `init`) [내 결정, 기존 suh-logger·pro-sejongpeia 네임스페이스 `kr.suhsaechan`]
  - 클라이언트 버전은 서버 릴리스(`v2.0.x`)와 분리 [내 결정]
- 공통 동작 (두 언어 같은 이름·의미):
  - `init(base_url, project, token, timeout_seconds=3)`; 기본 `base_url` = `https://ai.suhsaechan.kr/api/flask` (요청 경로 `/control/events`)
  - `notify(kind, title, fields=None, body=None, url=None, severity="info", dedupe_key=None) -> NotifyResult`
  - `notify_in_background(...)` (Python: 데몬 스레드, Java: `CompletableFuture`)
  - `NotifyResult(is_accepted: bool, status_code: int | None, error_code: str | None, is_deduplicated: bool)` — 예외를 던지지 않음 (네트워크 오류·시간 초과·init 전 호출 모두 결과로)
  - 헤더 `X-Control-Token`, `Content-Type: application/json; charset=utf-8`, 본문 UTF-8 JSON (`ensure_ascii=False`)
  - `fields`: 순서 유지 (Python: dict 또는 (이름, 값) 목록, Java: `LinkedHashMap` 또는 목록)
  - 토큰은 로그·`repr`·`toString`·예외 메시지에 넣지 않음
- 모바일 앱에서 쓰지 말 것, 개인정보는 보내는 쪽 판단 — 각 README 맨 앞에 명시
- 코드 규칙은 1~3단계와 같음 (한국어 짧은 주석, 영어 로그 접두사 `[control-tower client]`, 약어 금지, boolean is/has, 파일 300줄 미만). 커밋 접두는 같은 템플릿

## Review Focus

1. 관제소가 느리거나 죽었을 때 `notify`가 `timeout_seconds` 안에 돌아오고 예외를 던지지 않음 (Task 1, 2)
2. 한글 제목·항목이 깨지지 않고 서버 검증을 통과 (Task 1, 2)
3. `init` 없이 `notify` 호출 > 예외 없이 `error_code="not_initialized"` (Task 1, 2)
4. 토큰이 `repr`/`toString`/로그에 안 나옴 (Task 1, 2)
5. 클라이언트 본문이 규격 스키마·예시와 일치 (Task 1, 2)

---

### Task 1: Python 클라이언트

**Files:** Create `clients/python/pyproject.toml`, `clients/python/README.md`, `clients/python/LICENSE`(레포 LICENSE 복사 아님 — 레포 루트 LICENSE와 같은 MIT 문구, 출처 표기), `clients/python/src/suh_control_tower/__init__.py`, `client.py`, `result.py`, `clients/python/tests/test_client.py`, `tests/test_contract.py`

- [ ] **Step 1: 실패 테스트** — 로컬 `http.server`(127.0.0.1)로: 202 > is_accepted True, 202 deduplicated > is_deduplicated True, 400 `unknown_kind` > error_code, 401, 응답 지연 > 시간 초과 결과(timeout 0.2초 설정), 연결 거부 > 결과, init 전 > not_initialized, 한글 본문 그대로 전송, 헤더 토큰, `repr(client)`에 토큰 없음, `notify_in_background`가 즉시 반환; 계약: 클라이언트가 만드는 본문이 `docs/control-tower/events/events-v1.schema.json`을 만족(`jsonschema` 있으면, 없으면 skip)하고 `valid_custom_kind_fields.json` 예시와 같은 입력이면 같은 본문
- [ ] **Step 2~4**: 실패 확인 > 구현 > `cd clients/python && uv run --no-project --with pytest --with jsonschema python -m pytest -q` 통과, `uv build`로 wheel 생성 확인(게시 안 함)
- [ ] **Step 5: 커밋**

### Task 2: Java 클라이언트

**Files:** Create `clients/java/settings.gradle`, `build.gradle`, Gradle wrapper(`gradle wrapper --gradle-version 8.12.1`), `clients/java/README.md`, `src/main/java/kr/suhsaechan/controltower/ControlTower.java`(정적 진입점), `ControlTowerClient.java`, `NotifyResult.java`, `EventJsonWriter.java`(의존성 없는 JSON 작성, 이스케이프), `src/test/java/...`

- [ ] **Step 1: 실패 테스트** — JDK `com.sun.net.httpserver.HttpServer`(127.0.0.1)로 Task 1과 같은 경우들 + `EventJsonWriter` 이스케이프(따옴표, 역슬래시, 제어문자, 한글, 이모지) + 계약: 예시 `valid_custom_kind_fields.json` 입력과 같은 본문(JSON 비교는 테스트 안 최소 파서 또는 문자열 정규화)
- [ ] **Step 2~4**: 실패 확인 > 구현 > `cd clients/java && ./gradlew test build` 통과 (게시 설정 없음, `jar`만)
- [ ] **Step 5: 커밋**

### Task 3: 문서 연결

**Files:** Modify `docs/control-tower/events/README.md` (예시 절에 "라이브러리로 보내기" — Python·Java 사용법, 아직 게시 전이라 소스에서 설치하는 방법: `pip install ./clients/python`, Gradle `includeBuild` 또는 `publishToMavenLocal`), 설계 문서 5.5의 "4단계 시작 전 확인할 것"을 정해진 값으로 갱신

- [ ] 커밋
