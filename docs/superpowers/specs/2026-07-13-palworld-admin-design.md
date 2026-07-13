# Palworld 서버 관리자 페이지 설계

날짜: 2026-07-13
대상: `suh-ai-server` (Flask) + 로컬 Windows PC (Palworld 데디케이티드 서버 호스트)

## 목표

이 Windows PC에 Palworld 데디케이티드 서버를 구축하고, suh-ai-server(Flask)에 DaisyUI 기반 웹 관리자 페이지를 추가해 브라우저에서 서버를 전부 제어한다. 제어 범위: 시작/중지/재시작, 상태·접속자 확인, PalWorldSettings.ini 편집, 로그 조회, 세이브 백업.

## 아키텍처

```
[브라우저] ai.suhsaechan.kr/api/flask/admin
    │  X-API-Key: 최초 1회 modal 입력 → localStorage → 모든 fetch 헤더
    ▼
[nginx :11435] ── /api/flask/* → prefix 제거 → [Flask :5000]
                                                  │
                                    palworld_service.py
                                    ├─ NSSM 서비스 제어 (start/stop/restart)
                                    ├─ PalWorldSettings.ini 파싱/수정
                                    ├─ Palworld 공식 REST API (:8212, localhost 전용)
                                    │    → 서버 info, 플레이어 목록, 메트릭
                                    ├─ 로그 tail
                                    └─ 세이브 백업 (robocopy)
                                                  │
                                    [PalServer.exe] ← NSSM 서비스 "PalServer"
                                    C:\AI\palworld\steamcmd\steamapps\common\PalServer
```

### 핵심 결정

1. **프로세스 관리 = NSSM 서비스.** Flask 자체가 이미 NSSM으로 운영 중(기존 패턴). PalServer도 NSSM 서비스로 등록해 크래시 자동 재시작을 얻고, Flask는 `nssm start/stop PalServer`만 호출한다. subprocess 직접 관리는 Flask 재배포 시 게임 서버가 함께 죽으므로 배제.
2. **접속자/메트릭 = Palworld 공식 REST API** (포트 8212, `RESTAPIEnabled=True`, localhost 바인딩). Flask가 중계만 하고 외부 노출하지 않는다.
3. **인증 = 기존 nginx X-API-Key 재사용.** 관리 페이지 HTML/정적 파일만 nginx public 예외로 열고, 제어 API는 기존대로 키 필수. 별도 로그인 페이지·세션 시스템은 만들지 않는다 — 첫 진입 시 키가 없으면 DaisyUI modal로 입력받아 localStorage에 저장하는 것이 로그인 역할.

## 페이지 구조 (첫 페이지 = 대시보드)

```
/admin                  ← 관리 허브 대시보드 (첫 페이지)
  ├─ 카드: 팰월드 서버 관리 (상태 badge) → /admin/palworld
  ├─ 카드: OCR API → Swagger 링크
  ├─ 카드: Vision API → Swagger 링크
  └─ 카드: 서버 로그
/admin/palworld         ← 팰월드 전체 관리 페이지
```

- 대시보드 카드에 서비스 상태 badge 표시 (팰월드 running/stopped, Ollama 연결 여부).
- 이후 서비스 추가 시 카드만 추가하는 확장 구조.
- 기본 DaisyUI 컴포넌트만 사용 (navbar, card, stats, tabs, table, btn, badge, toggle, modal, mockup-code).

### /admin/palworld 화면 구성

- 상단: 상태 badge(running/stopped) + start/stop/restart 버튼
- `stats`: 접속자 수 / 서버 FPS / 업타임
- `tabs` 3개:
  - **설정**: ini 주요 항목 폼 (ServerName, ServerPassword, ServerPlayerMaxNum, bCrossplay, ExpRate, PalCaptureRate, DeathPenalty 등)
  - **로그**: `mockup-code` 블록, 자동 갱신
  - **백업**: 백업 목록 table + 즉시 백업 버튼

## 백엔드 (기존 계층 패턴 준수)

```
flask/
├─ router/
│   ├─ palworld_router.py   ← REST API + Swagger 스펙
│   └─ admin_router.py      ← /admin, /admin/palworld 페이지 렌더링
├─ service/
│   └─ palworld_service.py  ← NSSM 제어, ini 파싱, REST 중계, 백업
├─ config/
│   └─ palworld_config.py   ← 설치 경로, 포트, 서비스명, 백업 경로 상수
```

### API 엔드포인트

| Method | Path | 기능 |
|---|---|---|
| GET | `/palworld/status` | NSSM 서비스 상태 + 공식 REST info/players/metrics 통합 |
| POST | `/palworld/start` | 서비스 시작 |
| POST | `/palworld/stop` | 서비스 중지 |
| POST | `/palworld/restart` | 서비스 재시작 |
| GET | `/palworld/settings` | PalWorldSettings.ini 파싱 결과 |
| PUT | `/palworld/settings` | ini 수정 (서버 가동 중이면 409) |
| GET | `/palworld/logs?lines=200` | 로그 tail |
| GET | `/palworld/backups` | 백업 목록 |
| POST | `/palworld/backups` | 즉시 백업 실행 |

### 주의점 (필수 반영)

- **ini 저장 가드**: 서버 가동 중 ini 저장 시 종료 시점에 덮어씌워져 설정이 유실된다. PUT은 서버 실행 중이면 409 반환. UI는 "중지 → 저장 → 재시작" 원클릭 버튼을 선택 제공.
- **ini 파서**: `OptionSettings=(k=v,...)` 한 줄 포맷 전용 파서. 줄바꿈 삽입 금지를 파서가 보장.
- 백업: `robocopy`로 `SaveGames` → `C:\AI\palworld\backups\yyyyMMdd_HHmmss`. 자동 일일 백업은 Windows 작업 스케줄러(셋업 스크립트가 등록) — Flask는 무상태 유지.

## 프론트엔드

```
flask/
├─ frontend/
│   ├─ package.json      ← tailwindcss v4, daisyui v5 (최신)
│   └─ input.css
├─ templates/admin/
│   ├─ dashboard.html    ← Jinja2
│   └─ palworld.html
└─ static/
    ├─ css/app.css       ← Tailwind CLI 빌드 산출물 (git 커밋 포함 → 배포 시 npm 불필요)
    └─ js/palworld.js    ← 바닐라 JS fetch, 상태 5초 폴링
```

- URL은 전부 상대경로로 작성해 `/api/flask/` prefix 유무(외부/로컬 직접 접속)에 모두 동작.
- API Key 없으면 modal 입력 → localStorage 저장 → fetch 시 `X-API-Key` 헤더.

## 인프라

- **nginx.conf** public 엔드포인트 map에 추가:
  - `~^/api/flask/admin 1;`
  - `~^/api/flask/static/ 1;`
  - 제어 API(`/api/flask/palworld/*`)는 기존대로 키 필수.
- **setup-palworld.ps1** (신규, 1회 실행):
  1. SteamCMD 다운로드·압축 해제 (`C:\AI\palworld\steamcmd`)
  2. `login anonymous` + `app_update 2394010 validate`로 PalServer 설치
  3. 서버 1회 기동·종료 후 `DefaultPalWorldSettings.ini` 복사로 ini 초기 생성 (`RESTAPIEnabled=True`, `RESTAPIPort=8212` 포함)
  4. NSSM 서비스 "PalServer" 등록 — 기동 옵션 `-port=8211 -players=32 -useperfthreads -NoAsyncLoadingThread -UseMultithreadForDS` (크로스플레이 시 `-publiclobby` 추가)
  5. 방화벽 인바운드 8211/UDP, 27015/UDP 개방
  6. 일일 백업 작업 스케줄러 등록
- 공유기 포트포워딩은 자동화 불가 — 수동 안내 문서 제공.

## 구현 순서

1. `setup-palworld.ps1` — 서버 설치·기동 (이후 개발 검증의 전제)
2. 백엔드 `palworld_config` + `palworld_service` + `palworld_router` (TDD)
3. 프론트 빌드 환경(npm) + 대시보드 + 팰월드 페이지
4. nginx public 규칙 추가 + 배포

## 에러 처리

- NSSM/서비스 명령 실패 시 stderr를 포함한 500 응답, UI는 toast로 표시.
- 공식 REST API(:8212) 무응답 시(서버 꺼짐 등) status 응답에 `rest_available: false`로 degrade — 서비스 상태만 표시.
- ini 파싱 실패 시 원본 파일을 건드리지 않고 400 반환.

## 테스트

- ini 파서 단위 테스트 (파싱/직렬화 왕복, 특수문자·빈 값)
- 서비스 계층: NSSM 호출·REST 중계는 mock 기반 단위 테스트
- 라우터: Flask test client로 상태코드·가드(409) 검증
