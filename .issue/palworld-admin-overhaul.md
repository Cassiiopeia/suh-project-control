📝 현재 문제점
---

1차 구축(#46, v2.0.23) 이후 배포 검증에서 아래 문제가 확인됨

- **로그 기능이 사실상 동작하지 않음**
  - 팰월드 로그 탭이 NSSM 리다이렉트 파일(`palserver-stdout.log`)만 tail — 구버전 스크립트로 설치된 서버에는 파일이 없어 조용히 빈 목록 반환, 있어도 UE 초기화 몇 줄뿐
  - 장애 시 봐야 하는 진짜 로그는 `Pal\Saved\Logs\Pal.log`인데 읽지 않음
  - 접속/퇴장 이벤트는 팰월드 데디 서버가 어디에도 기록하지 않음 (REST 폴링으로 자체 생성 필요)
  - `readlines()` 전체 읽기라 로그 파일이 커지면 성능 문제
- **UI가 불친절함**
  - 아이콘이 전부 이모지/ASCII, 페이지 간 일관된 셸 없음, 대시보드는 카드 4개뿐
  - 대시보드의 "Flask 서버 로그" 카드가 팰월드 로그와 혼동을 유발
- **게임 접속 가이드 부재**
  - 접속 방법(주소/비밀번호)을 카톡으로 수동 공유 중 — 관리자 페이지에 실제 설정값과 연동된 가이드 필요

🛠️ 해결 방안 / 제안 기능
---

- **로그 정상화**: 로그 소스 4종(이벤트/게임 로그 `Pal.log`/stdout/stderr) 선택 조회, seek 기반 tail, 파일 부재 시 경로를 그대로 노출하는 진단 가능한 응답
- **접속/퇴장 이벤트 자체 생성**: Flask 백그라운드 폴러가 REST `/v1/api/players`를 10초 주기 폴링 → diff로 join/leave 감지, 서버 start/stop 이벤트 포함, JSONL 기록 + 로테이션
- **RomRom-BE 스타일 어드민 셸**: Jinja `base.html` 상속, daisyUI `drawer lg:drawer-open`(모바일 햄버거) + navbar + 다크모드 토글, Lucide 아이콘 로컬 번들로 이모지 전면 제거
- **접속 가이드**: `GET /palworld/guide`가 ini 실제 값(서버명/비밀번호/인원) + 공개 주소를 반환, daisyUI `steps` 3단계 안내 + 복사 버튼
- **대시보드 재설계** + Flask 로그 전용 페이지(`/admin/logs`) 분리

⚙️ 작업 내용
---

- [ ] `palworld_config.py` — `LOG_SOURCES` 4종, `PUBLIC_HOST`/`PUBLIC_PORT` 추가
- [ ] `palworld_service.py` — `tail_logs(source, lines)` seek 기반 재작성, 응답에 `log_file`/`exists`/`size_bytes` 포함
- [ ] `service/palworld_event_poller.py` 신규 — daemon thread 폴러, `diff_players()` 순수 함수, JSONL 기록 + 5MB 로테이션
- [ ] `palworld_router.py` — `logs?source=` 파라미터, `GET /palworld/guide` 추가, Swagger 문서 갱신
- [ ] `templates/admin/base.html` 신규 — drawer 셸 + navbar + 사이드바(대시보드/팰월드/API 문서/Flask 로그)
- [ ] `templates/admin/palworld.html` 재작성 — 상태 히어로 + 접속 가이드 + 탭(설정/로그/백업/플레이어), `confirm()` → daisyUI modal
- [ ] `templates/admin/dashboard.html` 재작성, `templates/admin/logs.html` 신규(`/admin/logs`)
- [ ] `static/js/log-viewer.js` 신규 — 공용 로그 뷰어(소스 전환/자동 새로고침/Error·Warning 하이라이트)
- [ ] Lucide 로컬 번들 (`frontend` npm 의존성 추가 → `static/js/vendor/` 복사)
- [ ] `setup-palworld.ps1` — NSSM 로그 로테이션(`AppRotateFiles`/`AppRotateBytes` 10MB)
- [ ] 테스트 — tail seek/소스 검증/`diff_players`/guide 엔드포인트/로테이션

설계 문서: `docs/superpowers/specs/2026-07-14-palworld-admin-overhaul-design.md`

🙋‍♂️ 담당자
---

- 백엔드: Cassiiopeia
- 프론트엔드: Cassiiopeia
