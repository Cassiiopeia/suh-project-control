<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * 각 벤치마크 배치 테스트 카드에 AI 친화적 마크다운 보고서 내보내기 버튼(원버튼 클립보드 복사 및 디스크 마크다운 파일 직접 다운로드) 기능 전격 도입

* **개선**
  * 수명 주기가 끝난 Blob 메모리 안전 취소 가드 및 비보안 HTTP/IP 주소에서도 무결 복사를 제공하는 클립보드 강제 셀렉션 폴백(Fallback) 구조 구축
  * 프론트엔드 비동기 요청 시 API-KEY 연동이 누락되는 사이드 이펙트를 원천 차단하기 위해 `apiFetch` 의무화 지침 및 형상 보호를 위한 `develop` 브랜치 중심 개발 운영 수칙 제정 후 `suh-ai-server/flask/CLAUDE.md` 영구 명문화

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

