<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * 관리 페이지에 "Claude 로그인" 화면 추가: 열면 로그인 메일을 자동으로 기다려 6자리 인증 코드를 표시
  * 인증 코드 복사 버튼, 메일 수신 시각, 남은 유효시간 표시
  * 메일 대기부터 코드 발급까지 진행 단계를 시각과 함께 표시
  * 코드 요청·발급·열람을 감사로그에 IP와 함께 기록하고 화면에서 최근 기록 확인

* **버그 수정**
  * 화면을 다시 열어도 아직 유효한 코드가 사라지지 않음
  * 유효시간이 지난 코드는 열린 화면에서도 자동으로 숨김
  * Gmail 연결이 멈춰도 대기 상태에 갇히지 않음

* **문서**
  * Claude 로그인 코드 화면 설계 문서와 구현 계획 추가

* **기타**
  * 배포 시 코드 확인용 브라우저를 서버에 자동 설치

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

