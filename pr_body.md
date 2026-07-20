<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * 서비스 안전성 및 책임 추적을 위한 독립적인 전용 감사로그 페이지(`/admin/audit`) 개설 (행위 필터링, KST 시간 표기, 프록시 IP 및 실행 환경 툴팁 표시, 상세 변경 diff 접기/펼치기 지원)
  * 정밀한 감사 데이터 가공 및 조회를 위한 외부 백엔드 API 엔드포인트(`GET /audit/logs`) 신설 및 Swagger 문서 업데이트

* **개선**
  * 공통 `@audited` 데코레이터를 새롭게 정의하여, API 호출 발생 시 실제 클라이언트 IP(XFF 헤더 파싱), 실행 브라우저(User-Agent) 및 성공/실패 여부를 가로채 자동 감사 기록하는 고도화 구조 도입
  * 데이터베이스 스키마 확장(마이그레이션 0002 적용)을 통해 IP/UA/성공여부 컬럼을 증설하고 기존 레코드 백필 보정 자동화
  * 팰월드, TTS 라우터의 수동 로깅 구조를 공통 데코레이터 규격으로 완벽 이관하고, 모델(MODEL) 관리 행위(삭제/다운로드/취소) 감사 신규 편입
  * 감사 로깅 수칙 누락 예방을 위한 개발자 가드레일 규약 문서(`suh-ai-server/flask/CLAUDE.md`) 정립

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

