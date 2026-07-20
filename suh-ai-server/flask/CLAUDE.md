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
