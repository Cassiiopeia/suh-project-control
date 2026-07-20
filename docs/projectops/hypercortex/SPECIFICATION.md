# SPECIFICATION

## [DATA_FLOW]

조작 버튼 클릭 시 클라이언트 상에서 동적으로 마크다운 문서가 인메모리(In-Memory) 조립되어 출력되는 흐름을 다이어그램으로 명시합니다.

```
+-------------------------------------------------------------------------------------------------------------------------+
|                                                      [ Client-Side ]                                                    |
|                                                                                                                         |
| 1. UI Click Event (btn-export-copy or btn-export-download)                                                               |
|                                                                                                                         |
| 2. Extract Batch Context:                                                                                               |
|    - Retrieve Batch ID, Prompt, Temperature, Format Mode, System Prompt.                                                |
|                                                                                                                         |
| 3. Parse Benchmark Table Data:                                                                                          |
|    - Iterate over `<tr>` elements in target `#batch-table-body-{batchId}`.                                               |
|    - Extract Model Name, Status, Total Time, Load Delay, Generation Time, Input Tokens, Output Tokens, Speed, and Schema.|
|                                                                                                                         |
| 4. Extract Model Response JSONs:                                                                                        |
|    - Iterate over `#batch-details-{batchId}` cards.                                                                     |
|    - Retrieve formatted string from each `<pre class="font-mono">` block.                                               |
|                                                                                                                         |
| 5. Assemble AI-Optimized Markdown:                                                                                      |
|    - Apply Structured Template, construct Markdown string.                                                              |
|                                                                                                                         |
| 6. Route Output:                                                                                                        |
|    +-------------------------------------------------------+------------------------------------------------------+     |
|    | If [Copy Button]                                      | If [Download Button]                                 |     |
|    |                                                       |                                                      |     |
|    | - Attempt navigator.clipboard.writeText               | - Create 가상 Blob with "text/markdown;charset=utf-8" |     |
|    | - On Failure: fallback to hidden <textarea> copy      | - Create 가상 <a> with URL.createObjectURL           |     |
|    | - Display "복사되었습니다!" Toast                    | - Trigger click() and automatically revoke object.   |     |
|    +-------------------------------------------------------+------------------------------------------------------+     |
|                                                                                                                         |
+-------------------------------------------------------------------------------------------------------------------------+
```

---

## [REPORT_TEMPLATE_SPECIFICATION]

동적으로 생성될 마크다운(`.md`) 파일 및 클립보드 복사용 명세 사양입니다.

```markdown
# Ollama Structured Output 벤치마크 보고서 (배치 #X)

- **수행 일시**: YYYY년 MM월 DD일 HH시 mm분 ss초
- **포맷 모드**: [none | "json" | JSON Schema]
- **온도 (Temperature)**: [값]
- **시스템 지침**: "[지침]"
- **테스트 프롬프트**: "[원문 프롬프트]"

## 1. 정량 지표 종합 비교
| 모델 | 상태 | 총 시간 | 로드 지연 | 추론 시간 | 입력 토큰 | 출력 토큰 | 추론 속도 | Schema 준수 여부 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| [모델 1] | 성공 | 1.2s | 0.1s | 1.0s | 45 | 110 | 110.0 tok/s | 정상 준수 |
| [모델 2] | 실패 | 0.5s | - | - | - | - | - | JSON 손상 |

## 2. 모델별 세부 출력 내역

### 🤖 [모델 1]
- **총 시간**: 1.2s (모델 로딩: 0.1s / 생성 추론: 1.0s)
- **토큰 규모**: 입력 45 토큰 / 출력 110 토큰 (생성 속도: 110.0 tok/s)
- **Schema 검증 상태**: 정상 준수
- **구조화 생성 결과 (JSON)**:
```json
{
  "key": "value"
}
```

---
```

---

## [FALLBACK_COPY_SPECIFICATION]

보안 컨텍스트(`HTTPS` 또는 `localhost` 이외의 도메인/IP 호출)에서 비보안으로 판단되어 클립보드 복사 API가 거부될 때 실행하는 정밀 폴백 자바스크립트 명세입니다:

```javascript
function fallbackCopyTextToClipboard(text) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  
  // 가시적 화면 오염을 막기 위해 뷰포트 영역에서 완전히 가림 처리
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    const successful = document.execCommand('copy');
    if (!successful) throw new Error('copy command returned false');
    showToast('클립보드에 보고서가 복사되었습니다.', 'success');
  } catch (err) {
    showToast('클립보드 복사에 실패했습니다. 마운트 상태를 확인하세요.', 'error');
  }

  document.body.removeChild(textArea);
}
```

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona
* **검토 의견**:
  - **API 정밀도 비판**: 테이블 내의 수집 대상 값들에 간혹 한글이나 공백 등이 불필요하게 가공되어 있을 수 있습니다. 가령 테이블 컬럼의 텍스트를 추출할 때 `innerText.trim()`을 확실하게 적용하여 불필요한 줄바꿈(\n)이 마크다운 표 테이블 정합성을 무너뜨리지 않도록 방어적인 전처리가 필요합니다.
  - **다운로드 수명 주기 관리**: 생성된 Blob URL은 다운로드 기동 즉시 `URL.revokeObjectURL(url)`을 실행하여 브라우저의 인메모리 누수를 엄격히 방지해야 합니다.
