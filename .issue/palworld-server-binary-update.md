📝 현재 문제점
---

- 오늘 팰월드 클라이언트 업데이트(v0.6.1.9) 이후 다른 컴퓨터에서 서버 접속 시 **"참가하려는 경기에 비호환 버전 게임이 실행중입니다. 게임 버전을 업그레이드해 보세요."** 메시지와 함께 접속 거부
- 서버 바이너리는 구버전(`v1.0.0.100427`) 그대로 — 클라이언트/서버 버전 불일치가 원인
- 어드민의 **재시작 버튼은 같은 구버전 바이너리를 재기동할 뿐이라 해결 불가**
- 서버 바이너리 업데이트는 SteamCMD(`+app_update 2394010 validate`)로만 가능한데, 현재 어드민에 이 기능이 없어 원격 조치 수단이 전무 — 게임 업데이트가 나올 때마다 재발하는 구조적 문제

🛠️ 해결 방안 / 제안 기능
---

- **어드민 "서버 업데이트" 기능 추가**: `POST /palworld/update`
  - 흐름: 세이브 백업 → PalServer 서비스 중지 → `steamcmd +login anonymous +app_update 2394010 validate +quit` → 서비스 시작
  - SteamCMD 다운로드가 수 분 걸리므로 **백그라운드 스레드**로 실행, `GET /palworld/update/status`로 진행 상태(단계·최근 출력) 폴링
  - 중복 실행 가드(업데이트 진행 중이면 409)
- **UI**: 서버 상태 카드에 "서버 업데이트" 버튼 + 진행 상태 표시(확인 모달에 "서버가 중지되고 수 분 소요" 경고)
- **감사로그 연동**: `SERVER_UPDATE` 액션 추가 — 누가(IP) 언제 업데이트했는지 기록 (#70 체계 재사용)
- 배포 즉시 어드민에서 버튼 클릭으로 이번 긴급 상황 해소 + 향후 게임 업데이트 때마다 재사용

⚙️ 작업 내용
---

- [ ] `palworld_service.py` — `update_server()`: 백업 → 서비스 중지 → steamcmd 실행 → 서비스 시작, 진행 상태/출력 버퍼 관리 (백그라운드 스레드, 중복 실행 가드)
- [ ] `palworld_router.py` — `POST /palworld/update` (202 + 감사 기록), `GET /palworld/update/status`, Swagger 갱신
- [ ] `audit_service.py` — `AuditAction.SERVER_UPDATE` enum 추가
- [ ] `palworld.html` / `palworld.js` — 서버 상태 카드에 "서버 업데이트" 버튼, 진행 상태 폴링·표시, 완료/실패 토스트
- [ ] 테스트 — 서비스 mock으로 흐름 검증(백업→중지→steamcmd→시작 순서, 실패 시 상태 failed), 라우터 202/409/감사 기록
- [ ] 배포 후 실서버에서 업데이트 실행 → 게임 버전 갱신 확인 → 클라이언트 접속 확인

🙋‍♂️ 담당자
---

- 백엔드: Cassiiopeia
- 프론트엔드: Cassiiopeia
