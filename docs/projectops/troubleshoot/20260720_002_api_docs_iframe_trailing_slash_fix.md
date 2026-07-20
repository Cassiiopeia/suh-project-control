### 문제 요약
API 문서 관리자 페이지 iframe 내 Swagger UI 미출력 결함 수정 및 X-API-Key 가이드화 | **타입**: Python Flask 백엔드 & Nginx 프록시 | **환경**: 로컬 개발(localhost:5000) 및 실 배포 서버(Nginx 역방향 프록시)

### 원인 분석
**근본 원인**:
1. **Nginx 미적용 로컬 개발 환경에서의 경로 불일치**: 기존 iframe `src` 속성이 숏 URL인 `{{ root }}/docs/swagger` 로 지정되어 있어, Nginx가 없는 로컬 환경에서는 `/docs/swagger` 에 대응하는 Flask 라우트가 존재하지 않아 **404 Not Found** 에러가 발생하여 화면이 표시되지 않았습니다.
2. **트레일링 슬래시 누락으로 인한 상대경로 오참조**: 브라우저에서 끝에 슬래시가 없는 주소(예: `/docs/swagger` 또는 `/api/flask/docs/swagger`)로 iframe을 렌더링하면, Swagger UI 내에서 상대 경로로 참조하는 정적 리소스(JS, CSS 등) 파일들이 `docs/swagger/...` 가 아닌 부모 폴더인 `docs/...` 로 요청되는 주소 오작동이 유발되어, 브라우저 콘솔에서 자산들을 로드하지 못하고 빈 화면만 노출되는 치명적인 오동작이 있었습니다.

**발생 메커니즘**:
- `templates/admin/api_docs.html` 내에 임베드된 iframe의 src가 `{{ root }}/docs/swagger` 로 정의됨.
- 실 배포 서버 주소인 `https://ai.suhsaechan.kr/api/flask/admin/api-docs` 로 접속 시 `root` 가 `..` 가 되어 iframe의 주소는 `https://ai.suhsaechan.kr/api/flask/docs/swagger` (끝에 슬래시 없음)가 됨.
- Nginx는 `/docs/swagger` 로 들어오는 요청에 대해 public endpoint로 바이패스하고 내부 rewrite(last)를 통해 `/api/flask/docs/swagger` 로 변환하여 Flask로 잘 전달하였으나, 브라우저가 응답받은 HTML 내의 상대 경로 리소스를 읽을 때 트레일링 슬래시 누락으로 인해 실제 정적 파일 요청을 `https://ai.suhsaechan.kr/api/flask/docs/` 디렉터리로 잘못 보냄 (404 발생).
- 로컬 환경에서는 Nginx가 아예 존재하지 않아 `/docs/swagger` 라는 경로 자체가 매핑되지 않아 무조건 404가 남.

---

### 해결 방법

#### Quick Fix (임시 조치)
- Nginx 설정에 모든 `/docs/swagger` 및 `/api/flask/docs/swagger` 요청에 대해 트레일링 슬래시(`/`)를 강제 리디렉션하는 규칙을 임시 추가합니다. (다만 Nginx 설정 재배포가 필요하며 로컬 개발 환경의 404 문제는 해결되지 않음.)

#### Root Fix (권장 및 실 적용)
1. **iframe src 물리 경로 지정 및 트레일링 슬래시 보장**: 숏 URL 대신 로컬과 실서버 모두에서 동일하게 물리 라우트로 접근할 수 있는 실제 백엔드 경로인 `{{ root }}/api/flask/docs/swagger/` 로 iframe 주소를 전격 보정했습니다. 이로 인해 트레일링 슬래시(`/`)가 확실히 공급되어 하위 정적 파일들이 완벽하게 로드됩니다.
2. **검증 테스트 코드 보정**: `test_admin_router.py` 내의 렌더링 검증 구문을 실제 물리 경로에 맞게 보정하여 완벽하게 통합 통과하도록 변경했습니다.

**코드 수정 사항**:

##### [1] `suh-ai-server/flask/templates/admin/api_docs.html` 수정
```html
<!-- 변경 전 -->
<iframe
  src="{{ root }}/docs/swagger"
  title="API Swagger 문서"
  class="w-full bg-base-100 rounded-box border border-base-300"
  style="height: calc(100vh - 11rem); min-height: 480px;"
></iframe>

<!-- 변경 후 -->
<iframe
  src="{{ root }}/api/flask/docs/swagger/"
  title="API Swagger 문서"
  class="w-full bg-base-100 rounded-box border border-base-300"
  style="height: calc(100vh - 11rem); min-height: 480px;"
></iframe>
```

##### [2] `suh-ai-server/flask/test/test_admin_router.py` 수정
```python
# 변경 전
def test_api_docs_page_renders_iframe(client):
    resp = client.get('/admin/api-docs')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'API 문서' in body
    assert '<iframe' in body
    assert '../docs/swagger' in body  # nginx 프리픽스 뒤에서도 동작하는 상대경로

# 변경 후
def test_api_docs_page_renders_iframe(client):
    resp = client.get('/admin/api-docs')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'API 문서' in body
    assert '<iframe' in body
    assert '../api/flask/docs/swagger/' in body  # 로컬 및 Nginx 역방향 프록시 모두 완벽 호환되는 실제 물리 상대경로와 트레일링 슬래시 보장
```

---

### API Key (X-API-Key) 사용 명세 안내

개발 시 혼선이 있었던 Swagger UI 화면에서의 API Key 필요 여부를 엄밀히 가이드라인화합니다.

1. **Swagger UI 자체(문서 화면) 로드 시**: **API Key가 전혀 불필요**합니다. Nginx의 public bypass 맵에 `/api/flask/docs/swagger` 가 매핑되어 있어, 누구나 제한 없이 API 명세 페이지에 접근해 열람할 수 있습니다.
2. **Swagger UI 내 "Try it out" 테스트 기동 시**: **API Key가 필수로 필요**합니다. 실제 백엔드 API 엔드포인트(예: `/ollama/chat`, `/ocr/*`)는 보안 검증 및 속도 제한(Rate Limiting)이 걸려 있어 유효한 `X-API-Key` 헤더를 필요로 합니다.
3. **인증 방법**: Swagger UI 우측 상단의 녹색 **`Authorize`** 버튼을 클릭한 후, 사용 중인 인가된 API Key를 입력하여 활성화하면 브라우저에 바인딩되어 헤더에 담겨 정상 테스트가 가능해집니다.

---

### 검증
1. **렌더링 테스트**: `pytest test/test_admin_router.py` 실행하여 정상 렌더링 및 `../api/flask/docs/swagger/` iframe 소스 렌더 완료 확인 (8개 테스트 전원 통과).
2. **로컬 브라우저 구동 검사**: `http://localhost:5000/admin/api-docs` 에 진입하면 iframe이 완벽하게 로컬 swagger-ui 정적 자산들을 404 없이 렌더링함을 완벽 검증.

### 재발 방지
- **경로 선언 시 트레일링 슬래시 규칙화**: 향후 iframe 또는 리소스 매핑 시, 파일 경로가 아닌 단일 폴더/인덱스 페이지를 가리킬 때는 자산 상대 경로 오작동을 피하기 위해 반드시 주소 끝에 `/` (트레일링 슬래시)를 의무 기입하도록 방어 코드 가이드라인을 강화함.
