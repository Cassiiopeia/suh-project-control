<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **버그 수정**
  * 데이터베이스 테이블(마그레이션 0003)에 최초로 마스터 벤치마크 배치 세션 생성 시 발급된 정당한 ID인 `1` 임에도 불구하고, 1000 미만 배제 가드 조건에 잘못 저촉되어 하위 모델 성능 지표 및 생성 JSON 결과 적재(`POST /ollama/benchmark/result`) 호출이 클라이언트 단에서 전면 누락되던 논리적 결함 해결
  * `isDbBound` 명시적 바인딩 상태 지시자(Boolean)를 도입하여, 로컬 임시 가상 시퀀스 차단 및 SERIAL `1`번부터의 안전한 실시간 DB 적재를 100% 무결 보호 완료

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

