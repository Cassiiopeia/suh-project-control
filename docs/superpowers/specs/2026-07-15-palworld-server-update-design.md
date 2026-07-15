# 팰월드 서버 바이너리 자동/수동 업데이트 (#73)

- 날짜: 2026-07-15
- 상태: 사용자 승인 (긴급 — 게임 클라이언트 업데이트로 버전 불일치 접속 불가)
- 관련: 이슈 https://github.com/Cassiiopeia/suh-project-control/issues/73

## 1. 배경

팰월드 클라이언트가 업데이트되면 구버전 서버에 "비호환 버전" 오류로 접속이 거부된다.
재시작은 같은 바이너리를 재기동할 뿐이라 해결 불가. SteamCMD(`+app_update 2394010 validate`)로
서버 바이너리를 갱신해야 하며, 현재 어드민에 이 수단이 없다.

## 2. 확정 요구사항

- **동적 감지**: 로컬 빌드 ID(`steamapps/appmanifest_2394010.acf`) vs 최신 빌드 ID(SteamCMD `app_info_print`)를
  백그라운드에서 30분마다 비교, UI에 "최신 상태/업데이트 필요" 배지 상시 표시
- **자동 업데이트**: 새 빌드 감지 시 접속자 0명이면 자동 실행 (백업 → 중지 → steamcmd → 시작).
  접속자가 있으면 강제 킥 방지를 위해 대기(다음 체크 때 재시도), UI에 "업데이트 대기" 표시
- **수동 버튼**: "서버 업데이트" 버튼 + 확인 모달. **steamcmd 실제 출력을 화면에 실시간 표시**(3초 폴링),
  단계 표시(백업 → 서버 중지 → 다운로드 → 서버 시작)
- **업데이트 전 백업**: 자동/수동 공통, 기존 백업 기능 재사용 (백업 실패는 경고만, 업데이트 진행)
- **실패 복구**: steamcmd 실패 시에도 서비스 재시작 시도 — 구버전으로라도 서버를 살려둔다
- **감사로그**: `SERVER_UPDATE` 액션 추가, trigger(manual/auto)와 행위자(IP 또는 system) 기록
- **중복 가드**: 업데이트 진행 중 재요청은 409

## 3. 아키텍처

### 3.1 `service/palworld_updater.py` (신규)

- 모듈 전역 상태(락 보호): `status(idle|running|done|failed)`, `step`, `log(deque 300줄)`,
  `trigger`, `error`, `started_at/finished_at` + 버전 정보 `local_build/remote_build/update_available/checked_at`
- `get_local_buildid()`: ACF 파일에서 `"buildid" "N"` 정규식 파싱 (파일 없으면 None)
- `get_remote_buildid()`: `steamcmd +login anonymous +app_info_update 1 +app_info_print 2394010 +quit`
  출력에서 `"public"` 브랜치의 buildid 파싱 (타임아웃 180초, 실패 None)
- `check_for_update()`: 두 값 비교 → 버전 정보 갱신·반환 (둘 중 하나라도 None이면 update_available=None=판단불가)
- `start_update(trigger, actor)`: running 가드 → 감사 기록 → 백그라운드 스레드 `_run_update()` 기동
- `_run_update()`: 백업(실패 시 경고 후 진행) → 서비스 중지 → steamcmd `app_update`(stdout 라인별 log 적재)
  → 서비스 시작 → done. 예외 시 failed + 서비스 시작 시도(finally)
- `auto_check_loop(interval=1800)`: check → 새 빌드 & 접속자 0명(또는 판단 불가) → `start_update('auto','system')`.
  접속자 있으면 스킵(다음 주기 재시도)

### 3.2 라우터 (`palworld_router.py`)

- `POST /palworld/update` → 진행 중 409, 아니면 start_update('manual', IP) → 202
- `GET /palworld/update/status` → 상태 + 버전 정보 + log tail (UI 폴링)
- `POST /palworld/update/check` → 동기 check_for_update() 결과 반환 ("지금 확인" 버튼)

### 3.3 UI (서버 상태 카드)

- 버전 배지: `확인 전 → 최신 상태(성공색) / 업데이트 필요(경고색, 빌드 표기) / 판단 불가`
- 버튼: "업데이트 확인", "서버 업데이트"(확인 모달: 서버 중지 + 수 분 소요 경고)
- 진행 패널(업데이트 중에만 표시): 단계 + steamcmd 출력 tail `<pre>`, 3초 폴링, 완료/실패 토스트.
  페이지 로드 시 진행 중이면 패널 자동 복원

### 3.4 기동 (`run.py`)

- 이벤트 폴러와 동일한 패턴으로 auto_check_loop 데몬 스레드 시작

## 4. 에러 처리

| 상황 | 동작 |
|------|------|
| steamcmd 실패/타임아웃 | status=failed + 서비스 재시작 시도 (서버 방치 금지) |
| 백업 실패 | 경고 로그만 남기고 업데이트 계속 (긴급 업데이트 우선) |
| ACF/원격 빌드 조회 실패 | update_available=None ("판단 불가" 표시), 자동 업데이트 안 함 |
| 접속자 수 판단 불가(REST 다운) | 0명으로 간주하고 자동 업데이트 진행 (서버가 죽은 상태면 어차피 갱신이 이득) |
| 업데이트 중 재요청 | 409 |

## 5. 테스트

- ACF/app_info 출력 파싱 (픽스처 문자열), check_for_update 비교 로직
- _run_update 순서(백업→중지→steamcmd→시작), steamcmd 실패 시 failed+재시작 시도, 백업 실패 시 계속
- start_update 중복 가드, 감사 기록(trigger/actor)
- 라우터 202/409/status 형태, 기존 테스트 회귀 없음

## 6. 범위 제외 (YAGNI)

- 업데이트 예약/스케줄 지정, 접속자 알림 브로드캐스트, 버전 롤백, steamcmd 설치 자동화(이미 설치됨)
