# TODO

## Phase 1: 요구사항 분석 (Requirement Analysis)
- [x] 프로젝트 컨텍스트 탐색 (ollama-test 및 CLAUDE.md 상태 파악) <!-- id: 1 -->
- [ ] 벤치마크 결과 내보내기 포맷 사양 구체화를 위한 명확한 질문 제기 <!-- id: 2 -->
- [ ] `docs/projectops/hypercortex/REQUIREMENT.md` 작성 및 리뷰어 검토 로그 기록 <!-- id: 3 -->

## Phase 2: 설계 (Design)
- [ ] 내보내기 버튼의 위치, 렌더링 템플릿(AI 전용 마크다운 등), CLAUDE.md 가이드 보완 설계 <!-- id: 4 -->
- [ ] `docs/projectops/hypercortex/DESIGN.md` 작성 (아키텍처, UI/UX 설계 포함) <!-- id: 5 -->
- [ ] 리뷰어 검토 로그 기록 및 설계안 확정 <!-- id: 6 -->

## Phase 3: 사양 정의 (Specification)
- [ ] AI 대화형 마크다운 변환 규격 명세서 `docs/projectops/hypercortex/SPECIFICATION.md` 작성 <!-- id: 7 -->
- [ ] 리뷰어 검토 로그 기록 <!-- id: 8 -->

## Phase 4: 개발 (Development)
- [ ] 벤치마크 결과 '보고서 내보내기' 버튼 추가 및 마크다운 파일 다운로드/클립보드 복사 로직 구현 <!-- id: 9 -->
- [ ] `suh-ai-server/flask/CLAUDE.md` 파일에 `apiFetch` 사용 의무화 및 `develop` 브랜치 기준 개발 규칙 영구 명문화 <!-- id: 10 -->
- [ ] 개발자 자체 리뷰 로그 작성 및 `docs/projectops/hypercortex/DEVELOPMENT.md` 기록 <!-- id: 11 -->

## Phase 5: 심층 코드 및 보안 감사 (Deep Code & Security Audit)
- [ ] `docs/projectops/hypercortex/QUALITY.md` 에 보안 및 성능 병목 검토 결과 기록 <!-- id: 12 -->
- [ ] 리뷰어 최종 승인 획득 <!-- id: 13 -->

## Phase 6: 테스트 (Testing)
- [ ] 내보낸 파일의 마크다운 정합성 및 인코딩, 클립보드 복사 안정성 테스트 수행 <!-- id: 14 -->
- [ ] 테스트 결과 데이터 기반 신뢰성 입증 및 `QUALITY.md` 반영 <!-- id: 15 -->
