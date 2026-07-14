# 팰월드 어드민 개편: 로그 정상화 + RomRom 스타일 UI + 접속 가이드

- 날짜: 2026-07-14
- 상태: 사용자 승인 대기
- 관련: `docs/superpowers/specs/2026-07-13-palworld-admin-design.md` (1차 구축)

## 1. 배경 / 문제

1차 구축(v2.0.23)으로 팰월드 서버 제어·설정·백업은 동작하지만, 배포 후 세 가지 문제가 확인됐다.

1. **로그가 쓸모없다.** 팰월드 로그 탭은 NSSM 리다이렉트 파일(`palserver-stdout.log`)만 tail한다.
   구버전 스크립트로 설치된 서버에는 이 파일이 없어 조용히 빈 목록을 반환하고, 파일이 있어도
   UE 초기화 몇 줄뿐이다. 개발자가 장애 시 봐야 하는 진짜 로그는 `Pal\Saved\Logs\Pal.log`다.
   또한 접속/퇴장 이벤트는 팰월드 데디 서버가 **어디에도 기록하지 않는다** — REST API 폴링으로
   자체 생성해야 한다(palworld-server-tool 등 커뮤니티 도구와 동일한 방식).
2. **UI가 불친절하다.** 아이콘이 전부 이모지, 대시보드는 카드 4개뿐, 페이지 간 일관된 셸이 없다.
3. **이용 가이드가 없다.** 게임 접속 방법(주소·비밀번호)을 카톡으로 수동 공유 중이다. 관리자
   페이지에 실제 설정값과 연동된 가이드가 있어야 한다.

## 2. 승인된 설계 방향 (브레인스토밍 결과)

- **전역 어드민 셸**: RomRom-BE `admin/layout.html` 패턴 이식 — daisyUI `drawer lg:drawer-open`
  (데스크톱 사이드바 고정, 모바일 햄버거 드로어) + navbar(페이지 제목, 다크모드 토글) + footer.
- **팰월드 페이지 내부**: 가이드 우선 랜딩 — 상태 히어로 → 접속 가이드 → 탭(설정/로그/백업/플레이어).
- **로그 소스 4종**: 이벤트(자체 생성) / 게임 로그(Pal.log) / stdout / stderr.
- **아이콘**: 이모지·ASCII 전면 제거, Lucide 아이콘(로컬 번들)으로 통일. daisyUI 네이티브 컴포넌트
  (stats, tabs, drawer, modal, toast, badge, menu) 최대 활용. `confirm()` 같은 브라우저 네이티브
  다이얼로그도 daisyUI modal로 교체.

## 3. 아키텍처

### 3.1 백엔드

#### 로그 소스 및 tail (`config/palworld_config.py`, `service/palworld_service.py`)

```python
LOG_SOURCES = {
    "events": os.path.join(PALWORLD_BASE_DIR, "logs", "palworld-events.jsonl"),
    "game":   os.path.join(PALSERVER_DIR, "Pal", "Saved", "Logs", "Pal.log"),
    "stdout": os.path.join(PALWORLD_BASE_DIR, "logs", "palserver-stdout.log"),
    "stderr": os.path.join(PALWORLD_BASE_DIR, "logs", "palserver-stderr.log"),
}
PUBLIC_HOST = "suh-project.synology.me"
PUBLIC_PORT = 8211
```

- `tail_logs(source: str, lines: int) -> dict`
  - `source`가 `LOG_SOURCES`에 없으면 `ValueError` (라우터에서 400).
  - **seek 기반 tail**: 파일 끝에서 최대 256KB만 읽어 마지막 N줄 반환 (`readlines()` 전체 읽기 제거).
    Pal.log는 수십 MB까지 자란다.
  - 반환: `{"source", "log_file"(절대경로), "exists"(bool), "size_bytes", "logs": [...]}`.
  - **파일이 없으면 빈 목록 + `exists: false` + 경로를 그대로 내려서** UI가 "이 경로에 파일이
    없습니다"를 표시한다. 지금처럼 조용히 `[]`만 반환하는 것이 혼란의 원인이었다.
- 기존 `GET /palworld/logs`는 `?source=` 파라미터 추가 (기본값 `game`).

#### 접속/퇴장 이벤트 폴러 (`service/palworld_event_poller.py` — 신규)

- Flask 앱 시작 시 daemon thread 1개 기동 (`app.py`에서 시작, waitress 환경 기준.
  debug reloader 이중 기동은 `WERKZEUG_RUN_MAIN` 가드).
- **10초 간격**으로:
  - `get_service_state()` 변화 감지 → `server_up` / `server_down` 이벤트.
  - 서버 running이면 REST `/v1/api/players` 조회(타임아웃 3초) → 이전 스냅샷과 diff →
    `join` / `leave` 이벤트. REST 실패는 조용히 스킵(다음 틱 재시도).
- diff는 순수 함수로 분리해 단위 테스트: `diff_players(prev: list, curr: list) -> (joined, left)`
  (기준 키: `userid`, 없으면 `name`).
- 기록 형식: `palworld-events.jsonl`에 JSON Lines —
  `{"ts": "2026-07-14T13:02:11", "type": "join", "player": {"name": "...", "level": 12}, "count": 3}`
- 로테이션: 쓰기 전 파일이 5MB 초과면 `.1`로 rename (1세대만 보관).
- 첫 기록 시 `logs` 디렉토리가 없으면 생성 (구버전 스크립트로 설치된 서버 대비).
- UI 표시는 프론트에서 한국어 문장으로 포맷 ("'suh' 접속 (3/32)").

#### 접속 가이드 API (`router/palworld_router.py`)

- `GET /palworld/guide` → `{"address": "suh-project.synology.me:8211", "server_name", "password",
  "max_players", "has_password"}`.
- `server_name`/`password`/`max_players`는 `PalWorldSettings.ini` 실제 값에서 읽는다 —
  설정을 바꾸면 가이드도 자동으로 따라온다. ini 부재 시 200 + 값 `null` (가이드 카드는 주소만 표시).
- Swagger 문서(`palworld_swagger.py`)에 `logs?source=` 변경과 `guide` 추가.

### 3.2 프론트엔드

#### 공용 셸 (`templates/admin/base.html` — 신규, Jinja 상속)

- RomRom `layout.html` 구조 이식: `drawer lg:drawer-open`, navbar(모바일 햄버거 · 페이지 제목 블록 ·
  다크모드 swap 토글), 사이드바(브랜드 + `menu` + active 하이라이트), footer.
- 사이드바 메뉴 4개: **대시보드**(`/admin`) · **팰월드 서버**(`/admin/palworld`) ·
  **API 문서**(`/docs/swagger`) · **Flask 로그**(`/admin/logs` — 신규 페이지).
- 다크모드: `data-theme` + `localStorage` 저장 (기본 dark 유지).
- 블록: `title`, `page_title`, `content`, `extra_js`.
- 기존 `admin-common.js`(apiFetch, API key modal, toast)는 셸에 포함.

#### 아이콘: Lucide 로컬 번들

- `frontend/package.json`에 `lucide` 추가 → 내부망 npm 미러로 설치 →
  `node_modules/lucide/dist/umd/lucide.min.js`를 `static/js/vendor/lucide.min.js`로 복사
  (빌드 스크립트에 copy 단계 추가). CDN 의존 없음.
- 사용법은 RomRom과 동일: `<i data-lucide="server" class="size-5"></i>` + `lucide.createIcons()`.
- **모든 이모지 제거** (🎮⚙️📋💾👥🔑🖥 → layout-dashboard, gamepad-2, settings, scroll-text,
  archive, users, key-round, server 등).

#### 대시보드 (`templates/admin/dashboard.html` — 재작성)

- 상단 `stats`: Flask 상태(health) · 팰월드 상태 + 접속자 수 · 팰월드 업타임.
- 서비스 카드 그리드: 팰월드 서버 관리 / API 문서(Swagger) — Lucide 아이콘 + 상태 배지 + 설명.
- Flask 로그 프리뷰 카드는 제거하고 사이드바 "Flask 로그" 페이지로 이동 (혼동 원인 제거).

#### Flask 로그 페이지 (`templates/admin/logs.html` — 신규, `/admin/logs`)

- 공용 로그 뷰어로 기존 `/logs` API 표시. level 필터(INFO/WARNING/ERROR) + 검색어 입력
  (API가 이미 지원하는 `level`/`search` 파라미터 활용).

#### 팰월드 페이지 (`templates/admin/palworld.html` — 재작성)

위에서 아래로:

1. **상태 히어로**: 상태 배지(RUNNING/STOPPED/NOT_INSTALLED) + 시작/중지/재시작 버튼
   (진행 중 `loading` 스피너, 확인은 daisyUI modal) + `stats`(접속자 n/max · FPS · 업타임).
2. **접속 가이드 카드**: `GET /palworld/guide` 연동.
   - 접속 순서 3단계 (daisyUI `steps` 컴포넌트): 타이틀 → 멀티플레이 참가하기(전용서버) →
     "비밀번호를 입력해주세요" 체크 → 주소·비밀번호 입력.
   - 주소·비밀번호는 실제 값 + 복사 버튼(clipboard API, 복사 성공 toast).
   - 서버 이름·최대 인원도 함께 표시. 비밀번호 없으면 "공개 서버 (비밀번호 없음)" 표시.
3. **탭** (daisyUI `tabs-box`): 설정 / 로그 / 백업 / 플레이어.
   - 설정: 기존 설정 폼 유지 (기능 변경 없음, 스타일만 셸에 맞춤).
   - 로그: 공용 로그 뷰어 — 소스 전환(이벤트·게임 로그·stdout·stderr), 라인 수(100/200/500),
     자동 새로고침 토글(10초) + 수동 새로고침, `Error`/`Warning` 라인 색상, 맨 아래일 때만
     자동 스크롤, 현재 파일 경로·크기 표시, 파일 없으면 경로 포함 안내.
   - 백업: 기존 기능 유지.
   - 플레이어: 기존 접속자 테이블을 탭으로 이동.

#### 공용 로그 뷰어 (`static/js/log-viewer.js` — 신규)

- 옵션(엔드포인트, 소스 목록, 필터 지원 여부)을 받아 로그 탭 UI를 렌더하는 단일 모듈.
- 팰월드 로그 탭과 Flask 로그 페이지가 공유. `mockup-code` 오용 제거, 일반 `<pre>` +
  색상 하이라이트로 교체.

### 3.3 운영 (`scripts/setup-palworld.ps1`)

- NSSM 로그 로테이션 추가: `AppRotateFiles 1`, `AppRotateOnline 1`, `AppRotateBytes 10485760`(10MB).
- 기존 "매 실행 시 설정 재적용" 블록에 포함 → 배포 서버에서 스크립트 재실행만으로 적용.

## 4. 에러 처리

- 로그 파일 부재: 200 + `exists: false` + 경로 → UI가 안내 문구 표시 (404 아님 — 소스 전환 UX 유지).
- 잘못된 `source`: 400.
- REST API 다운: 폴러는 스킵 후 재시도, 이벤트 로그에는 기록하지 않음 (서비스 상태 변화만 기록).
- ini 부재: guide는 200 + null 필드, 로그로 warning.
- 폴러 스레드 예외: 틱 단위 try/except로 스레드 생존 보장.

## 5. 테스트

`flask/test/`에 추가:

- `tail_logs`: 소스별 경로 선택, 미존재 파일(`exists: false`), seek tail 정확성(대용량 파일 마지막 N줄),
  잘못된 source의 ValueError.
- `diff_players`: 접속/퇴장/변화 없음/서버 재시작(전원 leave 후 join) 케이스.
- 이벤트 파일 로테이션(5MB 초과 시 rename).
- 라우터: `logs?source=` 검증(400), `guide` 응답 형태(ini 있음/없음).
- 기존 테스트(`test_palworld_*.py`) 회귀 없음.

## 6. 범위 제외 (YAGNI)

- RCON/치트 명령, 킥·밴 등 플레이어 조작.
- 이벤트 외부 알림(카톡/디스코드 웹훅).
- 로그 실시간 스트리밍(WebSocket/SSE) — 폴링 새로고침으로 충분.
- OCR/Vision 기능 및 인증 체계 변경.
- 접속/퇴장 이벤트의 DB 저장·통계 — JSONL 파일로 충분.

## 7. 마이그레이션 / 배포 메모

- 기존 `GET /palworld/logs` 호출은 `source` 기본값 `game`으로 자연 전환 (기존 stdout 대비
  오히려 정보량 증가).
- 배포 서버에서 `setup-palworld.ps1` 1회 재실행 필요 (NSSM 로테이션 적용).
- `frontend` 빌드 재실행 필요 (`npm install` — lucide 추가, `npm run build`).
