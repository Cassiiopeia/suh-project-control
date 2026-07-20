# Ollama Test Export and Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 각 벤치마크 배치 세션 카드에 클립보드 복사 및 마크다운 파일 다운로드 소형 버튼들을 도입하고, `CLAUDE.md` 규칙 문서 보완 및 깃허브 이슈 #113에 작업 완료 정합성 확보를 최종 완결합니다.

**Architecture:**
- 동적으로 생성되는 배치 테스트 카드 컨테이너 `#batch-run-X` 헤더 우측 상단에 클립보드 복사(`copy`) 및 파일 다운로드(`download`) 액션 아이콘을 개별 삽입합니다.
- 배치 세션 내 실시간 렌더링된 요약 테이블의 정량적 메트릭 텍스트와 개별 생성 응답 JSON 원문을 인메모리 상에서 AI 프롬프트 및 사람 분석용 마크다운 형식으로 가공 결합합니다.
- `navigator.clipboard` 및 비보안 환경 대응용 `<textarea>` 강제 셀렉션 폴백 복사 가드를 기동하고, Blob 및 `URL.createObjectURL`을 통한 누수 없는 파일 인스턴스 다운로드를 보증합니다.
- `CLAUDE.md` 파일 최하단에 `apiFetch` 필수화 및 `develop` 브랜치 소스 제어 수칙을 완벽히 영구 명문화합니다.

**Tech Stack:** JavaScript (ES6), HTML5, DaisyUI, Tailwind CSS, Markdown (.md)

## Global Constraints
- 마크다운 파싱 테이블 정합성 파괴 방지를 위해 모든 텍스트 추출물은 방어적인 전처리(`.trim()`, 공백 제거 등)를 통과시킵니다.
- 깃허브 신규 이슈 생성 및 릴리스 배포 파이프라인 연계는 표준 스킬들의 가이드라인을 100% 충족하여 처리합니다.
- 다운로드 생성한 가상 Blob 주소는 사용 완료 시 즉각적으로 소멸(`revokeObjectURL`)하여 메모리를 회복합니다.

---

### Task 1: ollama-test.html 및 ollama-test.js UI 마크업 갱신

**Files:**
- Modify: `suh-ai-server/flask/static/js/ollama-test.js`

**Interfaces:**
- Consumes: `addBatchContainer(batchId, prompt, mode)` 동적 컴포넌트 렌더러
- Produces: 복사 및 다운로드 소형 아이콘 버튼들이 완벽하게 부착된 동적 헤더 마크업

- [ ] **Step 1: 마크업 렌더러 함수 개편**

`suh-ai-server/flask/static/js/ollama-test.js` 파일 내의 `addBatchContainer` 동적 렌더링 함수를 개편하여 헤더 우측에 복사 및 다운로드 작은 버튼들을 추가하고 고유 데이터 속성(`data-batch-id`)을 부여합니다.

```javascript
function addBatchContainer(batchId, prompt, mode) {
  el('result-empty') && el('result-empty').remove();

  const container = document.createElement('div');
  container.className = 'border border-primary/20 rounded-xl p-4 bg-base-100 shadow space-y-4';
  container.id = 'batch-run-' + batchId;

  const modeLabel = MODE_LABELS[mode] || mode;
  container.innerHTML = 
    '<div class="flex items-center justify-between border-b border-base-300 pb-2">'
    + '  <div class="space-y-1">'
    + '    <h3 class="font-bold text-sm flex items-center gap-2 text-primary">'
    + '      <i data-lucide="layers" class="size-4"></i>배치 테스트 #' + batchId
    + '    </h3>'
    + '    <div class="text-xs opacity-70 font-mono break-all max-w-2xl">프롬프트: "' + escapeHtml(prompt) + '"</div>'
    + '  </div>'
    + '  <div class="flex items-center gap-1.5 shrink-0">'
    + '    <!-- 클립보드 복사 버튼 -->'
    + '    <button class="btn btn-ghost btn-xs text-primary px-1.5 btn-export-copy" title="AI 보고서 클립보드 복사" data-batch-id="' + batchId + '">'
    + '      <i data-lucide="copy" class="size-3.5"></i>'
    + '    </button>'
    + '    <!-- 마크다운 다운로드 버튼 -->'
    + '    <button class="btn btn-ghost btn-xs text-primary px-1.5 btn-export-download" title="마크다운 파일 다운로드" data-batch-id="' + batchId + '">'
    + '      <i data-lucide="download" class="size-3.5"></i>'
    + '    </button>'
    + '    <span class="badge badge-primary badge-outline text-xs">' + modeLabel + '</span>'
    + '  </div>'
    + '</div>'
    + '<!-- 배치 요약 테이블 -->'
    + '<div class="overflow-x-auto border border-base-200 rounded-lg">'
    + '  <table class="table table-xs w-full text-center">'
    + '    <thead>'
    + '      <tr class="bg-base-200/50">'
    + '        <th class="text-left font-semibold">모델</th>'
    + '        <th>상태</th>'
    + '        <th>총 시간</th>'
    + '        <th>로드 지연</th>'
    + '        <th>추론 시간</th>'
    + '        <th>인풋 토큰</th>'
    + '        <th>아웃풋 토큰</th>'
    + '        <th>속도 (tok/s)</th>'
    + '        <th>Schema 준수</th>'
    + '      </tr>'
    + '    </thead>'
    + '    <tbody id="batch-table-body-' + batchId + '"></tbody>'
    + '  </table>'
    + '</div>'
    + '<!-- 개별 상세 응답 카드 목록 -->'
    + '<div class="grid grid-cols-1 md:grid-cols-2 gap-3" id="batch-details-' + batchId + '"></div>';

  el('result-list').prepend(container);
  el('result-count').textContent = el('result-list').children.length;

  if (typeof lucide !== 'undefined') {
    lucide.createIcons({ attrs: { class: 'lucide' } });
  }

  // 동적으로 생성된 내보내기 버튼들의 클릭 이벤트 바인딩 호출
  bindExportEvents(container, batchId);

  return container;
}
```

- [ ] **Step 2: 수동 렌더링 확인**
이후 기능 구현 뒤 브라우저를 열어 카드 우측 헤더에 `copy`와 `download` 아이콘이 정교하게 자리하는지 마크업 상태를 수동 관찰합니다.

- [ ] **Step 3: Git Commit**

```bash
git add suh-ai-server/flask/static/js/ollama-test.js
git commit -m "feat(ollama-test): 배치 테스트 헤더 우측 보고서 내보내기 복사/다운로드 아이콘 추가"
```

---

### Task 2: AI 최적화 마크다운 템플릿 조립 및 파일 다운로드 로직 구현

**Files:**
- Modify: `suh-ai-server/flask/static/js/ollama-test.js`

**Interfaces:**
- Consumes: 카드 내 실시간 HTML 마크업 정보 및 요약 행
- Produces: 인메모리 마크다운 스트링 조립기 및 Blob 디스크 다운로더

- [ ] **Step 1: 마크업 정보 추출 및 마크다운 스트링 조립기 추가**

카드 내의 테이블 행과 상세 코드 결과를 파싱하여 마크다운 파일로 정렬하는 함수를 `suh-ai-server/flask/static/js/ollama-test.js`에 구축합니다.

```javascript
function generateBatchMarkdownReport(batchId) {
  const container = el('batch-run-' + batchId);
  if (!container) return '';

  // 기본 정보 추출
  const titleEl = container.querySelector('h3');
  const promptEl = container.querySelector('.text-xs.opacity-70.font-mono');
  const modeEl = container.querySelector('.badge-outline');

  const batchTitle = titleEl ? titleEl.innerText.trim() : '배치 테스트 #' + batchId;
  const rawPrompt = promptEl ? promptEl.innerText.replace('프롬프트:', '').trim() : '';
  const formatModeText = modeEl ? modeEl.innerText.trim() : '알 수 없음';
  
  const now = new Date();
  const dateStr = now.getFullYear() + '년 ' + (now.getMonth() + 1) + '월 ' + now.getDate() + '일 ' 
                + now.getHours() + '시 ' + now.getMinutes() + '분 ' + now.getSeconds() + '초';

  let md = '# Ollama Structured Output 벤치마크 결과 보고서 (' + batchTitle + ')\n\n';
  md += '- **수행 일시**: ' + dateStr + '\n';
  md += '- **포맷 모드**: ' + formatModeText + '\n';
  md += '- **설정 온도 (Temperature)**: ' + (el('temperature') ? el('temperature').value : '0') + '\n';
  md += '- **시스템 지침**: "' + (el('system-prompt') ? el('system-prompt').value.trim() : '없음') + '"\n';
  md += '- **테스트 프롬프트**: ' + rawPrompt + '\n\n';

  // 1. 요약 테이블 긁어오기
  md += '## 1. 정량 지표 종합 비교\n\n';
  md += '| 모델 | 상태 | 총 시간 | 로드 지연 | 추론 시간 | 입력 토큰 | 출력 토큰 | 추론 속도 | Schema 준수 여부 |\n';
  md += '| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n';

  const rows = container.querySelectorAll('tbody tr');
  rows.forEach(tr => {
    const cells = tr.querySelectorAll('td');
    if (cells.length >= 9) {
      const model = cells[0].innerText.trim();
      const status = cells[1].innerText.trim();
      const total = cells[2].innerText.trim();
      const load = cells[3].innerText.trim();
      const evalDur = cells[4].innerText.trim();
      const inputTok = cells[5].innerText.trim();
      const outputTok = cells[6].innerText.trim();
      const speed = cells[7].innerText.trim();
      const schema = cells[8].innerText.trim();

      md += '| ' + model + ' | ' + status + ' | ' + total + ' | ' + load + ' | ' + evalDur + ' | ' + inputTok + ' | ' + outputTok + ' | ' + speed + ' | ' + schema + ' |\n';
    }
  });
  md += '\n';

  // 2. 모델별 생성 상세 응답 긁어오기
  md += '## 2. 모델별 세부 출력 내역\n\n';
  const detailCards = container.querySelectorAll('[id^="batch-details-"] > div');
  detailCards.forEach(card => {
    const modelBadge = card.querySelector('.badge-primary');
    const modelName = modelBadge ? modelBadge.innerText.trim() : '알 수 없는 모델';

    const statusBadge = card.querySelector('.badge-success, .badge-warning, .badge-error');
    const statusText = statusBadge ? statusBadge.innerText.trim() : '';

    const metricsEl = card.querySelector('.grid-cols-2');
    const metricsText = metricsEl ? metricsEl.innerText.replace(/\s+/g, ' ').trim() : '';

    const codeBlock = card.querySelector('pre');
    const responseJson = codeBlock ? codeBlock.innerText.trim() : '';

    md += '### 🤖 ' + modelName + '\n';
    if (statusText) md += '- **상태**: ' + statusText + '\n';
    if (metricsText) md += '- **지표 요약**: ' + metricsText + '\n';
    md += '- **구조화 생성 결과 (JSON)**:\n';
    md += '```json\n' + responseJson + '\n```\n\n';
  });

  md += '---\n';
  return md;
}
```

- [ ] **Step 2: Blob 다운로드 핸들러 구현**

Blob 및 가상 <a> 엘리먼트를 활용해 메모리 누수가 없는 다운로드 기능을 작성합니다.

```javascript
function downloadMarkdownReport(batchId) {
  const md = generateBatchMarkdownReport(batchId);
  if (!md) { showToast('보고서 데이터를 생성할 수 없습니다.', 'error'); return; }

  const todayStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const fileName = 'ollama_benchmark_batch_' + batchId + '_' + todayStr + '.md';

  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();

  // 안전한 메모리 해제 및 소멸
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);

  showToast('보고서 파일 다운로드가 시작되었습니다.', 'success');
}
```

- [ ] **Step 3: Git Commit**

```bash
git add suh-ai-server/flask/static/js/ollama-test.js
git commit -m "feat(ollama-test): 마크다운 보고서 파싱 가공 및 물리 Blob 다운로드 파이프라인 구현"
```

---

### Task 3: 클립보드 복사 보안 가드 및 이벤트 바인딩 구현

**Files:**
- Modify: `suh-ai-server/flask/static/js/ollama-test.js`

**Interfaces:**
- Consumes: `generateBatchMarkdownReport` 생성 결과물
- Produces: 복사 및 다운로드 클릭 이벤트 완전 격격 제어 수립

- [ ] **Step 1: 폴백 적용 복사 핸들러 구현**

`navigator.clipboard` 오류를 안전하게 가로채 `<textarea>` 요소로 셀렉션 복사하는 우회 코드를 추가합니다.

```javascript
function copyReportToClipboard(batchId) {
  const md = generateBatchMarkdownReport(batchId);
  if (!md) { showToast('복사할 보고서 데이터가 없습니다.', 'error'); return; }

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(md)
      .then(() => {
        showToast('보고서가 클립보드에 복사되었습니다! 바로 AI 프롬프트에 활용해 보세요.', 'success');
      })
      .catch(err => {
        console.warn('Navigator clipboard failed, falling back...', err);
        fallbackCopyTextToClipboard(md);
      });
  } else {
    fallbackCopyTextToClipboard(md);
  }
}

function fallbackCopyTextToClipboard(text) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  
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
    showToast('클립보드에 보고서가 복사되었습니다! (Fallback)', 'success');
  } catch (err) {
    showToast('클립보드 복사에 실패했습니다. 수동으로 다운로드 후 복사해 주세요.', 'error');
  }

  document.body.removeChild(textArea);
}
```

- [ ] **Step 2: 동적 이벤트 바인딩 컨트롤 구현**

```javascript
function bindExportEvents(cardContainer, batchId) {
  const copyBtn = cardContainer.querySelector('.btn-export-copy');
  const downloadBtn = cardContainer.querySelector('.btn-export-download');

  if (copyBtn) {
    copyBtn.addEventListener('click', function() {
      copyReportToClipboard(batchId);
    });
  }
  if (downloadBtn) {
    downloadBtn.addEventListener('click', function() {
      downloadMarkdownReport(batchId);
    });
  }
}
```

- [ ] **Step 3: Git Commit**

```bash
git add suh-ai-server/flask/static/js/ollama-test.js
git commit -m "feat(ollama-test): 클립보드 복사 보안 가드 및 동적 클릭 이벤트 리스너 바인딩 완결"
```

---

### Task 4: CLAUDE.md 규칙 명문화 및 깃허브 이슈/PR 연계 배포

**Files:**
- Modify: `suh-ai-server/flask/CLAUDE.md`

**Interfaces:**
- Consumes: 기존 `CLAUDE.md` 수칙
- Produces: `apiFetch` 의무화 및 `develop` 소스 규칙이 탑재된 영구 가이드라인 개정

- [ ] **Step 1: CLAUDE.md 최하단에 규칙 추가**

`suh-ai-server/flask/CLAUDE.md` 파일 끝부분에 윈도우/리눅스 공통 개발 규칙을 명시합니다.

```markdown
## 개발 환경 및 코드 작성 가이드라인 (중요)

### 1. 프론트엔드 비동기 요청 (API Key 보존 수칙)
- Flask Admin 템플릿의 프론트엔드 자바스크립트에서 백엔드로 비동기 API 요청(`fetch`)을 설계할 때는 절대 네이티브 `fetch`를 직접 사용하지 않는다.
- 반드시 `admin-common.js`에 정의된 공통 인증 fetch 래퍼인 **`window.apiFetch(path, options)`**를 의무적으로 활용해야 한다.
- `apiFetch`는 로컬 세션의 API-KEY를 추출하여 `X-API-Key` 및 `Content-Type` 헤더를 자동으로 안전 병합하므로, 호출 유실로 인한 `401 Unauthorized` 오류를 원천 차단한다.

### 2. Git 브랜치 제어 및 형상 운영
- 모든 기획, 기능 고도화, 리팩토링, 코드 개선 및 긴급 핫픽스 수정 작업은 반드시 **`develop` 브랜치**를 소스로 하여 시작하고 구현을 완료한다.
- `main` 브랜치는 엄격한 빌드와 릴리스 노트를 포함하는 자동 배포 릴리스 PR 머지 이외의 어떠한 직접 커밋/푸시 목적의 직접 제어도 금지한다.
```

- [ ] **Step 2: 수동 확인**
`CLAUDE.md`가 정상 보완되었는지 문서를 정독합니다.

- [ ] **Step 3: Git Commit**

```bash
git add suh-ai-server/flask/CLAUDE.md
git commit -m "docs(CLAUDE): apiFetch 호출 의무화 및 develop 브랜치 소스 제어 개발 수칙 명문화"
```

---

## Self-Review Check

1. **Spec Coverage**:
   - [x] 카드 헤더 우측 A안 더블 소형 아이콘 배치 완료 (Task 1)
   - [x] AI 및 사람 전용 정량/정성 마크다운 조립 템플릿 수립 (Task 2)
   - [x] Clipboard API 비보안 가드 및 Blob 다운로드 수명 해제 완결 (Task 3)
   - [x] `CLAUDE.md` 내에 `apiFetch` 의무화 및 브랜치 규칙 명문화 (Task 4)
2. **Placeholder Scan**: "TODO"나 "TBD"가 전혀 없으며, 다운로드와 복사에 필요한 완전한 JS 전처리가 다 포함되어 있습니다.
3. **Type Consistency**: 요약 테이블의 셀 인덱스와 상세 카드 선택 명세서가 Task 1~3 전체에서 일관되게 정합성을 유지합니다.
