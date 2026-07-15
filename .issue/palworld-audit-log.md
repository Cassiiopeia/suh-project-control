📝 현재 문제점
---

- 팰월드 관리자 페이지는 카톡방 공유 단일 API Key로 누구나 서버 제어/설정 수정이 가능
- **누가(어느 IP) 언제 무엇을 바꿨는지 기록이 전혀 없음** — 설정이 바뀌거나 서버가 재시작돼도 추적 불가
- 관리 행위에 대한 감사(audit) 체계 필요

🛠️ 해결 방안 / 제안 기능
---

- **PostgreSQL 감사로그**: 관리 행위(서버 시작/중지/재시작, 설정 수정, 백업 생성)를 `suh_ai_server` DB의 `audit_log` 테이블에 기록
- **확장 가능한 2단 구조**: `category`(PALWORLD/SYSTEM/...) + `action` — 코드 enum + DB VARCHAR (Spring `@Enumerated(STRING)` 철학), 향후 다른 서비스도 동일 테이블 사용
- **설정 변경 diff 기록**: 실제로 달라진 키만 `{from → to}` JSONB로 저장
- **행위자**: 클라이언트 IP (`X-Forwarded-For` → `remote_addr`)
- **마이그레이션**: `yoyo-migrations` (Flyway 방식 — 순수 SQL 파일 + 이력 테이블, 앱 기동 시 자동 적용)
- **조회 UI**: 팰월드 로그 탭에 "감사" 소스 추가 (`GET /palworld/logs?source=audit` — 기존 뷰어 재사용)
- **Fail-open**: DB 다운 시 감사 기록만 스킵(warning), 관리 행위·앱 기동은 정상
- **시크릿 관리**: `flask/.env`(gitignore) + GitHub Secret `FLASK_ENV_FILE` 통째 등록 → CICD가 서버에 동적 생성 (레포 노출 0)

⚙️ 작업 내용
---

- [ ] `flask/migrations/0001__create_audit_log.sql` — audit_log 테이블 + 인덱스
- [ ] `config/db_config.py` — python-dotenv 로드, `AUDIT_DATABASE_URL` (미설정 시 감사 비활성)
- [ ] `service/audit_service.py` — `AuditCategory`/`AuditAction` enum, `record()`(fail-open), `list_logs()`(뷰어 응답 형태)
- [ ] `run.py` — 기동 시 yoyo 마이그레이션 자동 적용 (DB 다운 시 스킵)
- [ ] `palworld_router.py` — start/stop/restart/settings(diff)/backup 성공 시 기록, `source=audit` 조회 분기, Swagger 갱신
- [ ] `palworld.js` — 로그 소스에 "감사" 추가
- [ ] `.gitignore` — `suh-ai-server/flask/.env`
- [ ] `SUH-AI-PROJECT-CONTROL.yaml` — Secret → 서버 `.env` 생성 스텝 (deploy-flask 실행 전)
- [ ] `requirements.txt` — psycopg2-binary, yoyo-migrations, python-dotenv
- [ ] GitHub Secret `FLASK_ENV_FILE` 등록 (API)
- [ ] 테스트 — record fail-open, settings diff, client_ip, 라우터 기록/분기, 기존 49개 회귀 없음

설계 문서: `docs/superpowers/specs/2026-07-14-palworld-audit-log-design.md`

🙋‍♂️ 담당자
---

- 백엔드: Cassiiopeia
- 프론트엔드: Cassiiopeia
