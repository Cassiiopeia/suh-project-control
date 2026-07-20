# TODO

## Phase 1: 요구사항 분석 (Requirement Analysis)
- [x] Ollama Hang 현상 정밀 진단 및 윈도우 로그 고정 경로 식별 완료 <!-- id: 1 -->
- [ ] Ollama 제어 UI 세부 스펙 확정을 위한 명확한 질문 제기 <!-- id: 2 -->
- [ ] `docs/projectops/hypercortex/REQUIREMENT.md` 작성 및 리뷰어 검토 로그 기록 <!-- id: 3 -->

## Phase 2: 설계 (Design)
- [ ] Ollama 윈도우 프로세스/서비스 제어 파워쉘 핸들러 및 VRAM 모델 PS API 아키텍처 설계 <!-- id: 4 -->
- [ ] `docs/projectops/hypercortex/DESIGN.md` 작성 (아키텍처, UI/UX 설계 포함) <!-- id: 5 -->
- [ ] 리뷰어 검토 로그 기록 및 설계안 확정 <!-- id: 6 -->

## Phase 3: 사양 정의 (Specification)
- [ ] `POST /ollama/control/<action>` 및 `GET /ollama/ps` API 명세 및 윈도우 로그 스트리밍 규격서 `docs/projectops/hypercortex/SPECIFICATION.md` 작성 <!-- id: 7 -->
- [ ] 리뷰어 검토 로그 기록 <!-- id: 8 -->

## Phase 4: 개발 (Development)
- [ ] 백엔드 Ollama 프로세스(Restart, Status) 및 VRAM 모델 PS/Unload 제어 서비스 및 라우터 구현 <!-- id: 9 -->
- [ ] 윈도우 Ollama `server.log` 경로 자동 감지 및 실시간 로그 뷰어 연계 구현 <!-- id: 10 -->
- [ ] Flask Admin 내 독립적인 'Ollama 제어' 웹 탭 UI 화면 전격 개설 및 연동 <!-- id: 11 -->
- [ ] 개발자 자체 리뷰 로그 작성 및 `docs/projectops/hypercortex/DEVELOPMENT.md` 기록 <!-- id: 12 -->

## Phase 5: 심층 코드 및 보안 감사 (Deep Code & Security Audit)
- [ ] `docs/projectops/hypercortex/QUALITY.md` 에 백그라운드 프로세스 기동 보안 리스크 진단 및 완화 결과 기록 <!-- id: 13 -->
- [ ] 리뷰어 최종 승인 획득 <!-- id: 14 -->

## Phase 6: 테스트 (Testing)
- [ ] Ollama 프로세스 강제 죽이기 및 재기동, VRAM 청소 기동 시나리오 정합 테스트 수행 <!-- id: 15 -->
- [ ] 테스트 결과 데이터 기반 신뢰성 입증 및 `QUALITY.md` 반영 <!-- id: 16 -->
