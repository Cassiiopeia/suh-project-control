# suh-ai-server/flask 작업 규칙

## 감사로그 (필수)

**상태를 변경하는 관리 엔드포인트(POST/PUT/DELETE)를 추가하면 반드시 `@audited` 데코레이터를 부착한다.**
조회(GET)와 일반 사용 API(예: `POST /tts` 합성)는 감사 대상이 아니다.

### 사용법 (`util/audit_helper.py`)

```python
from service.audit_service import AuditCategory, AuditAction
from util.audit_helper import audited, set_audit_detail, set_audit_action, skip_audit

@bp.route('/example', methods=['POST'])
@audited(AuditCategory.PALWORLD, AuditAction.SERVER_START)
def example():
    set_audit_detail({'name': '...'})   # 선택: 상세 정보 병합 (여러 번 호출 가능)
    ...
```

- IP(XFF 분해)·User-Agent·성공/실패(status < 400)는 데코레이터가 자동 수집·판정한다.
- 액션이 런타임에 정해지면 `@audited(카테고리)`만 달고 검증 통과 직후 `set_audit_action()` 호출.
  action 미지정 상태로 끝나면 기록되지 않는다 (검증 실패 404 등은 감사 대상 아님).
- 의미 없는 기록(예: 실변경 없는 설정 저장)은 `skip_audit()`로 생략한다.
- 요청 컨텍스트 밖(백그라운드 스레드)은 `audit_service.record()`를 직접 호출한다 (예: `palworld_updater`).

### 새 카테고리/행위 추가 절차 (마이그레이션 불필요)

1. `service/audit_service.py`의 `AuditCategory`/`AuditAction` enum에 값 추가
2. `static/js/audit.js`의 `ACTION_LABELS`와 `ACTIONS_BY_CATEGORY`에 한국어 라벨 추가
   (라벨이 없어도 UI는 enum 코드 원문으로 표시되어 깨지지 않는다)
3. 카테고리 추가 시 `audit.js`의 `CATEGORY_META`와 `templates/admin/audit.html`의
   카테고리 셀렉트 옵션에도 추가

### 정책

- fail-open: 감사 DB 다운/URL 미설정이 관리 행위를 절대 막지 않는다
- `audit_log.actor_ip`(XFF 원문)는 감사 원본이므로 삭제/변경 금지
- 실패한 관리 행위 시도도 `success=false`로 기록된다
- DB 스키마 변경은 `migrations/`에 yoyo SQL 파일 추가 (앱 기동 시 자동 적용)

## 프론트 CSS

`static/css/app.css`는 Tailwind 4 + daisyUI 빌드 산출물(purge)이다.
템플릿/JS에서 새 클래스를 쓰면 `frontend/`에서 `npm run build`로 재빌드해 함께 커밋한다.

## 테스트

`suh-ai-server/flask`에서 `python3 -m pytest test/ -q`

## 개발 환경 및 코드 작성 가이드라인 (중요)

### 1. 프론트엔드 비동기 요청 (API Key 보존 수칙)
- Flask Admin 템플릿의 프론트엔드 자바스크립트에서 백엔드로 비동기 API 요청(`fetch`)을 설계할 때는 절대 네이티브 `fetch`를 직접 사용하지 않는다.
- 반드시 `admin-common.js`에 정의된 공통 인증 fetch 래퍼인 **`window.apiFetch(path, options)`**를 의무적으로 활용해야 한다.
- `apiFetch`는 로컬 세션의 API-KEY를 추출하여 `X-API-Key` 및 `Content-Type` 헤더를 자동으로 안전 병합하므로, 호출 유실로 인한 `401 Unauthorized` 오류를 원천 차단한다.

### 2. Git 브랜치 제어 및 형상 운영
- 모든 기획, 기능 고도화, 리팩토링, 코드 개선 및 긴급 핫픽스 수정 작업은 반드시 **`develop` 브랜치**를 소스로 하여 시작하고 구현을 완료한다.
- `main` 브랜치는 엄격한 빌드와 릴리스 노트를 포함하는 자동 배포 릴리스 PR 머지 이외의 어떠한 직접 커밋/푸시 목적의 직접 제어도 금지한다.

### 3. GitHub 이슈 핸들링 절대 수칙 (매우 중요)
- **이슈를 임의로 닫지(Close) 않는다.** 작업이 성공적으로 완료되었을 때 `close-issue`를 호출하여 이슈를 닫는 행위는 엄격히 금지된다.
- 작업 완료 시, 오직 해당 이슈의 라벨(Label)을 **`작업완료`**로 전환하기만 해야 한다.
