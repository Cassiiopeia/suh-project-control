<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * PostgreSQL 연계 벤치마크 데이터베이스 스키마 확장(마이그레이션 0003 적용) 완료: 배치 마스터(`benchmark_batch`) 및 세부 성능 결과(`benchmark_result`) 1:N 릴레이션 테이블 및 검색 지연 차단용 인덱스 추가
  * 마스터 생성, 실시간 결과 적재, 이력 목록 및 세부 정보 지연 패치를 지원하는 백엔드 CRUD REST API 4종 전면 구현
  * 벤치마크 중 임시 OOM 및 네트워크 단절 등으로 인해 실패한 특정 모델만 골라 단 한 번의 터치로 다시 가동하는 '실패 모델 일괄/개별 재실행(Retry)' 컨트롤 기어 탑재
  * 하단에 '과거 벤치마크 테스트 이력' 복원 대시보드를 신설하여, 아코디언 전개 시 Lazy-Loading 방식으로 당시의 정량 비교 테이블과 상세 응답 JSON 카드를 고스란히 화면에 영구 복원하는 뷰 구축
  * 과거 이력 카드에서 당시 실험 조건(프롬프트, 스키마, 온도 등)을 편집기로 즉시 리로딩해 주는 '이 조건으로 다시 실험' 리커버리 편의 기능 도입

* **개선**
  * 동일 모델 중복 적재 방지를 위한 복합 제약 조건 부여 및 `ON CONFLICT DO UPDATE` (UPSERT) 기법을 장착하여 데이터 저장 무결성 완전 수호
  * 과거 카드 상에서 재시도 기동 시 입력창 데이터와 오염 꼬임이 없도록, 각 카드 엘리먼트 내부에 원천 파라미터 컨텍스트(`dataset`)를 격리 캡슐화 바인딩 처리

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

