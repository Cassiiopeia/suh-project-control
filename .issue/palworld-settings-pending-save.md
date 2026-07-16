📝 현재 문제점
---

- 서버 실행 중 설정 저장 시 **409로 거부**("서버 가동 중에는 저장할 수 없습니다") — 사용자는 저장 자체가 안 되니 설정 변경이 감사로그에도 남지 않음
- 막아둔 이유: PalServer는 **종료 시 메모리 설정값으로 ini를 덮어써서**, 실행 중 파일에 저장해도 중지/재시작 순간 저장분이 유실됨
- 하지만 "저장 불가"보다 "저장해두고 재시작 시 적용" UX가 낫고, 감사로그도 저장 시점에 남길 수 있음

🛠️ 해결 방안 / 제안 기능
---

- **대기(pending) 저장 방식**: 서버 실행 중 저장 → 변경분을 `pending_settings.json`에 보관 + **감사로그 SETTINGS_UPDATE 즉시 기록** + 응답 "재시작 시 적용됩니다"
- **자동 적용**: 서버가 중지되는 모든 경로(수동 중지, 재시작, 자동/수동 서버 업데이트)에서 **중지 완료 직후** pending을 ini에 적용 후 pending 삭제 — PalServer의 종료 시 ini 덮어쓰기가 끝난 뒤라 유실 없음
- 서버 정지 중 저장은 기존대로 즉시 ini 반영 (pending 있으면 함께 적용)
- **UI**: 저장 성공 시 실행 중이면 "저장 완료 — 서버 재시작 시 적용됩니다" 안내, 적용 대기 변경이 있으면 설정 탭 상단에 표시. 기존 "중지 → 저장 → 재시작" 버튼 유지

⚙️ 작업 내용
---

- [ ] `config/palworld_config.py` — `PENDING_SETTINGS_PATH` 상수
- [ ] `service/palworld_service.py` — `update_settings()` 실행 중이면 pending 병합 저장(applied=False 반환), `stop()`/`restart()` 중지 직후 pending 적용, 정지 중 저장 시 pending 선적용
- [ ] `router/palworld_router.py` — 409 분기 제거, applied 여부 응답, 감사 diff에 pending 여부 포함
- [ ] `palworld.js` — 저장 응답 applied=False 시 안내 토스트, 적용 대기 표시, 실행 중 경고 문구 갱신
- [ ] 테스트 — pending 저장/적용/감사 기록, 기존 409 테스트 대체, 회귀 없음

🙋‍♂️ 담당자
---

- 백엔드/프론트: Cassiiopeia
