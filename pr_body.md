<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * 팀 브레인 만들기를 미리 확인하는 dry_run 을 지원해요 (아무것도 바꾸지 않고 계획과 포트를 보여 줘요)

* **버그 수정**
  * 이미 있는 빈 팀 DB 를 지우지 않고 그 자리에서 준비해 받아 써요
  * 다시 만들기를 실행할 때마다 쓰기 계정 권한을 다시 적용해요 (기존 비밀번호는 그대로예요)
  * 팀 브레인이 아닌 객체가 있는 DB 는 아무것도 지우지 않고 멈춘 뒤 이유를 알려 줘요

* **개선**
  * 팀 브레인 만들기 실패 응답에 오류 코드, 다음 할 일, 끝난 단계를 함께 보여 줘요

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

