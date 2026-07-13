📝 현재 문제점
---

- Palworld 멀티플레이를 위해 24시간 가동되는 데디케이티드 서버가 필요하나, 현재 Windows 서버 PC에 구축되어 있지 않다.
- 서버를 구축하더라도 시작/중지, 설정 변경(PalWorldSettings.ini), 로그 확인, 세이브 백업을 매번 원격 접속으로 수동 처리해야 하는 운영 부담이 있다.
- suh-ai-server(Flask)는 현재 OCR/Vision REST API 전용으로 웹 UI가 전혀 없어, 서버 상태를 한눈에 보고 제어할 관리 화면이 부재하다.
- 서버 가동 중 ini를 수정하면 종료 시 덮어씌워져 설정이 유실되는 함정이 있어, 이를 시스템적으로 막는 장치가 필요하다.

🛠️ 해결 방안 / 제안 기능
---

- Windows 서버 PC에 SteamCMD 기반 Palworld 데디케이티드 서버를 설치하고 NSSM 서비스로 등록해 부팅 자동 시작·크래시 자동 재시작을 확보한다.
- suh-ai-server(Flask)에 DaisyUI(Tailwind CSS v4 + daisyUI v5) 기반 웹 관리자 페이지를 추가한다.
  - 첫 페이지는 관리 허브 대시보드(`/admin`) — 서비스 카드(팰월드 서버 관리, OCR API, Vision API, 서버 로그) 배치, 카드별 상태 badge 표시
  - 팰월드 관리 카드 클릭 시 전용 관리 페이지(`/admin/palworld`)로 이동해 전체 제어
- 팰월드 관리 페이지 기능:
  - 서버 시작/중지/재시작 (NSSM 서비스 제어)
  - 상태 조회: 가동 여부, 접속자 목록, 서버 메트릭 (Palworld 공식 REST API 연동, localhost 전용)
  - PalWorldSettings.ini 웹 편집 — 서버 가동 중 저장 시 409 반환으로 설정 유실 방지
  - 서버 로그 실시간 조회
  - 세이브 백업 목록 조회 및 즉시 백업 실행, 일일 자동 백업(작업 스케줄러)
- 인증은 기존 nginx X-API-Key 체계를 재사용한다 — 관리 페이지·정적 파일만 public 예외로 열고, 제어 API는 키 필수. 별도 로그인 시스템은 만들지 않는다.
- 상세 설계 문서: `docs/superpowers/specs/2026-07-13-palworld-admin-design.md`

⚙️ 작업 내용
---

- [ ] `setup-palworld.ps1` 작성 — SteamCMD 설치, PalServer 설치(app 2394010), ini 초기 생성(RESTAPIEnabled 포함), NSSM 서비스 등록, Windows 방화벽 UDP 8211/27015 개방, 일일 백업 스케줄러 등록
- [ ] Flask 백엔드 — `config/palworld_config.py`, `service/palworld_service.py`(NSSM 제어·ini 파서·REST 중계·백업), `router/palworld_router.py`(status/start/stop/restart/settings/logs/backups API + Swagger 스펙)
- [ ] Flask 페이지 라우터 — `router/admin_router.py` (`/admin` 대시보드, `/admin/palworld`)
- [ ] 프론트엔드 — `frontend/`(npm, Tailwind CLI 빌드 환경), `templates/admin/dashboard.html`, `templates/admin/palworld.html`, `static/js/palworld.js` (API Key modal + localStorage, 상태 5초 폴링)
- [ ] nginx.conf — 관리 페이지·정적 파일 public 엔드포인트 규칙 추가
- [ ] 테스트 — ini 파서 단위 테스트, 서비스 mock 테스트, 라우터 상태코드·409 가드 검증
- [ ] 공유기 UDP 8211 포트포워딩(수동) 및 외부 접속 검증

🙋‍♂️ 담당자
---

- 백엔드: Cassiiopeia
- 프론트엔드: Cassiiopeia
