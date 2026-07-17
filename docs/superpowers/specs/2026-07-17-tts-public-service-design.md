# 외부 공개 TTS 서비스 설계 (2단계) — 보이스 클로닝 API + 사용 가이드

- 날짜: 2026-07-17
- 상태: 승인됨
- 선행: `2026-07-17-tts-engine-manager-design.md` (1단계 — 배포 완료)

## 목표

외부의 여러 사용자가 API 키만으로 TTS를 사용할 수 있게 한다:
1. **보이스 클로닝**: API 키 소지자 누구나 자기 음성을 등록하고, 그 목소리로 합성
2. **사용 가이드**: 사용법을 관리자 페이지(`/admin/tts`) 안 섹션에 게시 — nginx상 admin 페이지는 공개 열람이라 링크 공유로 외부인도 볼 수 있음
3. **운영 보호**: 텍스트 길이 제한 등

## 확정 결정

- **보이스 등록 권한**: API 키 소지자 누구나 (nginx가 `/tts/*` 쓰기 요청에 키 검증)
- **가이드 위치**: `/admin/tts` 페이지 내 접이식 섹션
- **저장 방식(A안)**: 음성 파일 `data/tts-voices/` + 메타 `data/tts_voices.json` — DB 비의존(fail-open 철학), SCP 배포 경로 밖이라 배포에 안 씻겨나감
- **보이스는 CosyVoice 전용** — Kokoro는 내장 프리셋만 사용

## API

| 엔드포인트 | 인증 | 설명 |
|---|---|---|
| `GET /tts/voices` | 공개 | 내장 + 사용자 보이스 통합 목록 (id, name, builtin, engine, created_at) |
| `POST /tts/voices` | API 키 | multipart: `name` + `file`(WAV, 3~30초, 10MB 이하) → `{voice_id}` |
| `DELETE /tts/voices/<id>` | API 키 | 사용자 보이스 삭제. 내장 보이스는 403 |

- `voice_id` = `u_` + uuid 8자 (내장 id와 네임스페이스 분리), 저장 파일명은 uuid로 정규화(경로 조작 차단)
- 업로드 검증: WAV(RIFF 헤더), 크기 10MB 이하, 재생 길이 3~30초 (float32 WAV도 허용 — RIFF 헤더 + fmt 파싱)
- 등록/삭제는 감사로그 기록 (`TTS_VOICE_ADD` / `TTS_VOICE_DELETE`)
- `POST /tts`의 `voice`에 사용자 보이스 id 지정 시 해당 파일로 제로샷 클로닝 합성
- `POST /tts` 텍스트 500자 제한 (초과 400)

## 구성 요소

- `service/tts/voice_store.py` [신규]: 사용자 보이스 CRUD — 파일 저장/삭제, JSON 메타 관리(스레드 락), 검증
- `service/tts/adapters.py` [수정]: CosyVoice 어댑터가 내장(TTS_REFS_DIR) + 사용자(data/tts-voices) 보이스 경로를 모두 해석
- `router/tts_router.py` [수정]: `/tts/voices` CRUD 3개 + `/tts` 텍스트 길이 제한
- `service/tts_service.py` [수정]: `get_engines_state()`의 cosyvoice voices에 사용자 보이스 병합
- `templates/admin/tts.html` + `static/js/tts.js` [수정]: 보이스 관리 카드(업로드 폼 + 목록 + 미리듣기 + 삭제), API 사용 가이드 접이식 섹션
- `router/tts_swagger.py` [수정]: voices 경로 문서화

## 사용 가이드 내용 (웹 게시 항목)

1. 시작하기 — API 키 발급(관리자 요청) 및 `X-API-Key` 헤더 사용법
2. 엔진 상태 조회 — `GET /tts/engines` (실행 중 엔진·보이스 확인)
3. 음성 합성 — `POST /tts` 명세 + 예제 코드 3종 (curl / Python / JavaScript, 복사 버튼)
4. 보이스 클로닝 — 등록 절차(10초 내외 녹음 권장) + **타인 음성 무단 클로닝 금지 고지**
5. 제한사항 — 한 번에 1개 엔진 실행(전환은 관리자), rate limit(nginx 100r/s), 텍스트 500자
6. Swagger 문서 링크

## 에러 처리

- 업로드 검증 실패 → 400 + 한국어 사유
- 존재하지 않는 voice id로 합성 → CosyVoice는 첫 내장 보이스 폴백(1단계 동작 유지)
- 내장 보이스 삭제 시도 → 403

## 테스트

- voice_store: 등록/목록/삭제, 검증 실패(비WAV·길이 초과·크기 초과), 내장 삭제 거부
- 라우터: CRUD 응답 코드, 텍스트 500자 제한
- 어댑터: 사용자 보이스 id로 합성 시 올바른 파일 경로 사용

## 스코프 제외 (3단계 후보)

키별 사용량 통계, 보이스 소유자 개념, 스트리밍 합성, MP3 업로드 지원
