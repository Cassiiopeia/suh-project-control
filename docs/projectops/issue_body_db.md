## 개요
다중 모델 벤치마크 테스트 결과의 휘발성을 극복하기 위해 관계형 데이터베이스(PostgreSQL) 연계 영구 보존 체계를 도입하고, 테스트 중 OOM/네트워크 단절 등으로 일부 실패한 모델만 선별 기동하는 "실패 모델 재실행(Retry)" 대시보드와 "과거 이력 역추적" 아코디언 뷰를 전면 구축합니다.

## 세부 마일스톤 및 구현 사양
1. **RDB 기반 DB 스키마 설계 (마이그레이션 0003)**
   - 마스터 세션(`benchmark_batch`) 및 개별 모델별 정량/정성 성능 지표(`benchmark_result`) 1:N 릴레이션 정의
   - `UNIQUE (batch_id, model_name)` 복합 제약 및 `ON CONFLICT DO UPDATE` (UPSERT) 안전장치를 설정해 정합성 무결성 보호
2. **백엔드 CRUD REST API 개설 및 보호**
   - `POST /ollama/benchmark/batch`: 마스터 정보 생성 및 `batch_id` 발급
   - `POST /ollama/benchmark/result`: 비동기 루프별 개별 모델 UPSERT 기동
   - `GET /ollama/benchmark/history`: 최근 15개 배치 이력 역순 마스터 목록 조회
   - `GET /ollama/benchmark/history/<batch_id>`: 세부 지표 및 응답 JSON Lazy Loading 조회
   - 모든 경로에 `@audited` 감사 로그 및 `X-API-Key` 검증 미들웨어 보호막 장착
3. **실패 모델 일괄/단일 재실행 (Retry) 기능**
   - 배치 카드 상단에 "실패 모델만 일괄 재실행" 컨트롤 및 요약 표 내 개별 모델별 "재시도(Retry)" 단독 기동 아이콘 배치
   - 현재 화면 에디터가 오염되어도 오작동을 차단하기 위해, 각 카드 엘리먼트에 당시 보존된 프롬프트/스키마 컨텍스트(`dataset`)를 격리 바인딩하여 안전 구동
   - 결과 갱신 완료 즉시 원격 DB 에 UPSERT 실시간 연동
4. **과거 벤치마크 이력 아코디언 대시보드**
   - 페이지 하단에 과거 테스트 이력 카드를 신설
   - 아코디언을 클릭해 펼치는 순간(On Expand) 하위 결과를 Lazy-Loading으로 패치하여 실시간 때와 100% 동일한 요약 테이블 및 JSON 카드 레이아웃 완벽 복원
   - 복원된 과거 카드 위에서도 실패 모델 재실행 완벽 기동 보증
