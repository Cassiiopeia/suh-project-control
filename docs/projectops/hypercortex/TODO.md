# TODO

## Phase 1: 요구사항 분석 (Requirement Analysis)
- [x] 모델 관리 및 테스트 페이지의 패밀리 오발별 및 필터 부족 문제 인지 <!-- id: 1 -->
- [x] 시놀로지 환경의 타임아웃/VRAM 청소 정책 복합 병목 정밀 분석 완료 <!-- id: 2 -->
- [x] `docs/projectops/hypercortex/REQUIREMENT.md` 수립 및 리뷰어 승인 완료 <!-- id: 3 -->

## Phase 2: 설계 (Design)
- [ ] DaisyUI 활용 다차원 필터 컨트롤 패널 레이아웃 설계 <!-- id: 4 -->
- [ ] hf.co 모델 명칭에 기반한 실제 아키텍처 정교한 매핑 추출 규칙 설계 <!-- id: 5 -->
- [ ] `docs/projectops/hypercortex/DESIGN.md` 작성 및 리뷰어 검토 로그 기록 <!-- id: 6 -->

## Phase 3: 사양 정의 (Specification)
- [ ] 공통 JS 유틸리티를 통한 필터 연산 및 `getFamily` 추출 규격 정의 <!-- id: 7 -->
- [ ] `docs/projectops/hypercortex/SPECIFICATION.md` 작성 및 리뷰어 검토 로그 기록 <!-- id: 8 -->

## Phase 4: 개발 (Development)
- [x] API 문서 페이지 iframe 트레일링 슬래시 및 물리 경로 수정 (`api_docs.html`) <!-- id: 17 -->
- [x] API 문서 렌더 테스트 코드 및 상대경로 검증 보정 (`test_admin_router.py`) <!-- id: 18 -->
- [ ] 공통 필터 로직 및 `getFamily` 추출 로직의 `admin-common.js` 또는 개별 모듈 이식 <!-- id: 9 -->
- [ ] 모델 관리 페이지 (`models.html`, `models.js`) DaisyUI 필터 및 그룹화 카드 구현 <!-- id: 10 -->
- [ ] Ollama 테스트 페이지 (`ollama-test.html`, `ollama-test.js`) DaisyUI 필터 및 가시성 기반 일괄 선택 구현 <!-- id: 11 -->
- [ ] 개발자 자체 리뷰 로그 작성 및 `docs/projectops/hypercortex/DEVELOPMENT.md` 기록 <!-- id: 12 -->

## Phase 5: 심층 코드 및 보안 감사 (Deep Code & Security Audit)
- [ ] `docs/projectops/hypercortex/QUALITY.md` 에 대량 모델 필터링 시 메모리 및 렌더링 성능 검토 기록 <!-- id: 13 -->
- [ ] 리뷰어 최종 승인 획득 <!-- id: 14 -->

## Phase 6: 테스트 (Testing)
- [ ] 슬라이더 조작, 텍스트 검색, 체크박스 유지 상태, 전체 선택 가시 한정 정합성 검증 테스트 수행 <!-- id: 15 -->
- [ ] 테스트 결과 기록 및 `QUALITY.md` 반영 <!-- id: 16 -->
