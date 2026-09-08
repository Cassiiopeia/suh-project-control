# Sunshine(Moonlight) 원격 스트리밍 제어 페이지 설계

- 이슈: https://github.com/Cassiiopeia/suh-project-control/issues/138
- 작성일: 2026-09-08
- 분류: bounded (기존 Ollama 관리 페이지 구조를 그대로 미러링)

## 배경

AI 서버(Windows)에는 Sunshine 2025.829가 `SunshineService`로 상시 구동되고, 외부에서 Moonlight로
원격 접속한다. 새 기기 페어링은 서버 화면의 Windows 알림 또는 localhost 전용 웹 UI에서 PIN을
입력해야 해서 원격지에서는 불가능하다. 세션이 BUSY로 남거나 서비스가 죽어도 확인할 수단이 없다.

조사 결과(2026-09-08): 외부망 → 공인 IP 스트림은 정상 동작한다(TCP 47984/47989/48010, UDP 47998~48000
모두 포워딩됨). Sunshine 웹 API(`https://127.0.0.1:47990/api/*`)는 Basic 인증으로 200 응답한다.
Flask는 NSSM으로 LocalSystem 권한에서 돌며 설정은 `flask/.env`에서 읽는다.

## 화면 (`/admin/sunshine`)

카드 4개, `templates/admin/ollama.html` 레이아웃을 따른다.

1. **상태 카드**: 서비스 상태 배지, 스트림 상태(FREE/BUSY)와 실행 중 앱, 외부 접속 주소.
   버튼: 서비스 시작 / 중지 / 재시작, 실행 중 세션 강제 종료.
2. **PIN 페어링 카드**: PIN(4자리)과 기기 이름 입력 → 승인. Windows 알림 창을 대신한다.
3. **페어링된 기기 카드**: 이름·UUID 목록, 개별 해제 버튼(확인 모달).
4. **로그 카드**: Sunshine 로그 tail, 5초 자동 새로고침.

## 백엔드

### 설정 `config/sunshine_config.py`

| 키 | 기본값 | 출처 |
|---|---|---|
| `SUNSHINE_API_URL` | `https://127.0.0.1:47990` | env |
| `SUNSHINE_SERVERINFO_URL` | `http://127.0.0.1:47989/serverinfo` | env |
| `SUNSHINE_WEB_USER` / `SUNSHINE_WEB_PASSWORD` | 없음 | env (`.env`) |
| `SUNSHINE_SERVICE_NAME` | `SunshineService` | env |
| `SUNSHINE_PUBLIC_HOST` | `suh-project.synology.me` | 상수 |
| `SUNSHINE_API_TIMEOUT_SECONDS` | 5 | 상수 |

`.env`는 `db_config`가 이미 `load_dotenv`로 로드하므로 `os.environ`만 읽는다.

### 서비스 `service/sunshine_service.py`

`SunshineService` 클래스. `requests` 세션(Basic auth, `verify=False`, 자체서명 경고 억제).

- `get_status()` → `{service_running, api_reachable, credentials_configured, stream_state, current_app, version, host_name, public_host}`
  - 서비스 상태: `sc query` 대신 PowerShell `Get-Service` 결과 파싱 (ollama_service와 동일 방식)
  - 스트림 상태: 47989 `/serverinfo` XML의 `state`, `currentgame`을 파싱해 앱 ID → 이름 매핑
- `list_clients()` → `[{name, uuid}]` (`GET /api/clients/list`)
- `unpair_client(uuid)` (`POST /api/clients/unpair`)
- `submit_pin(pin, name)` (`POST /api/pin`) — 4자리 숫자 검증은 라우터에서
- `close_session()` (`POST /api/apps/close`)
- `read_logs(lines)` (`GET /api/logs`, 줄 단위 tail)
- `start_service()` / `stop_service()` / `restart_service()` — PowerShell `Start-Service`/`Stop-Service`

API 오류는 `SunshineApiError(message, status_code)`로 통일해 라우터가 502/401로 매핑한다.

### 라우터 `router/sunshine_router.py` (`sunshine_bp`)

| 메서드 | 경로 | 감사 액션 |
|---|---|---|
| GET | `/sunshine/status` | - |
| GET | `/sunshine/clients` | - |
| POST | `/sunshine/clients/unpair` `{uuid}` | `SUNSHINE_UNPAIR` |
| POST | `/sunshine/pin` `{pin, name}` | `SUNSHINE_PAIR` |
| POST | `/sunshine/session/close` | `SUNSHINE_SESSION_CLOSE` |
| POST | `/sunshine/control/<start\|stop\|restart>` | `SUNSHINE_START/STOP/RESTART` |
| GET | `/sunshine/logs?lines=200` | - |

감사 카테고리 `SUNSHINE` 신설. 검증 실패(400)는 감사 대상 아님(액션 미지정 상태에서 반환).

### 프론트

- `templates/admin/sunshine.html`, `static/js/sunshine.js` (`apiFetch`만 사용, 5초 폴링)
- `templates/admin/base.html` 사이드바에 "Sunshine 관리" 항목(아이콘 `monitor-play`)
- `router/admin_router.py`에 `/admin/sunshine` 렌더 라우트
- `static/js/audit.js`, `templates/admin/audit.html`에 카테고리·액션 라벨 추가
- 새 CSS 클래스는 기존 빌드 산출물에 있는 것만 사용한다(재빌드 회피).

## 테스트

- `test/test_sunshine_service.py`: serverinfo XML 파싱, 앱 ID→이름 매핑, API 오류 매핑,
  PowerShell 호출 인자 (subprocess 모킹)
- `test/test_sunshine_router.py`: 각 엔드포인트 성공/검증실패/API오류 응답, 감사 액션 세팅
- `test/test_admin_router.py`: `/admin/sunshine` 렌더 및 no-emoji

## 운영

- 서버 `flask/.env`에 `SUNSHINE_WEB_USER`, `SUNSHINE_WEB_PASSWORD` 추가 후 Flask 서비스 재시작(1회)
- 자격증명 미설정 시 상태 카드에 안내 배너를 띄우고 서비스 제어와 serverinfo 조회는 계속 동작한다.

## 범위 밖

- 대시보드 서비스 제어 카드에 Sunshine 추가
- Sunshine 설정(`/api/config`) 편집, 앱 목록 편집
