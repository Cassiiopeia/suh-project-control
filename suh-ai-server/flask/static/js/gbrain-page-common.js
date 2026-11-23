/* gbrain 관리 화면 공통 (#213): 요소 찾기, 응답 본문 읽기, 실패 문구 + 에러 코드, 되돌릴 수 없는 작업 확인 창 (#221)
   사용처: gbrain*.js 전부 (이 파일을 먼저 로드), 확인 창 마크업은 gbrain.html #gbrain-confirm-modal */
window.gbrainPage = (function () {
  // Windows 서비스 상태 코드 > 표시 문구 (개인·팀 브레인 공통, 그 외는 원문)
  const SERVICE_STATE_LABELS = {
    running: '구동 중', stopped: '정지됨', start_pending: '시작 중', stop_pending: '중지 중',
    not_installed: '미설치', unknown: '확인 불가',
  };

  function getElement(id) { return document.getElementById(id); }

  // JSON 이 아니거나 비어 있으면 빈 객체 (실패 응답도 문구를 만들 수 있게)
  async function readResponseBody(response) {
    try { return await response.json(); } catch (error) { return {}; }
  }

  // 실패 문구 + 에러 코드 (화면 문구 규칙: 오류에는 코드 함께)
  function describeFailure(responseBody, fallbackMessage) {
    return (responseBody.error || fallbackMessage) + (responseBody.code ? ' [' + responseBody.code + ']' : '');
  }

  /* 되돌릴 수 없는 작업 확인 창: 제목 + 설명 + 결과 목록 > 확인이면 true (취소·바깥 클릭·Esc 는 false)
     options: title, message, consequences(문구 배열), confirmLabel */
  function confirmDanger(options) {
    const modal = getElement('gbrain-confirm-modal');
    getElement('gbrain-confirm-title').textContent = options.title;
    getElement('gbrain-confirm-message').textContent = options.message || '';
    getElement('gbrain-confirm-message').hidden = !options.message;
    const consequenceList = getElement('gbrain-confirm-consequences');
    consequenceList.replaceChildren.apply(consequenceList, (options.consequences || []).map(function (text) {
      const item = document.createElement('li');
      item.textContent = text;
      return item;
    }));
    getElement('gbrain-confirm-accept').textContent = options.confirmLabel;
    modal.returnValue = '';
    return new Promise(function (resolve) {
      modal.addEventListener('close', function () { resolve(modal.returnValue === 'accept'); }, { once: true });
      modal.showModal();
      getElement('gbrain-confirm-cancel').focus();  // 실수로 Enter 를 눌러도 취소
    });
  }

  return {
    getElement: getElement, readResponseBody: readResponseBody, describeFailure: describeFailure, confirmDanger: confirmDanger,
    SERVICE_STATE_LABELS: SERVICE_STATE_LABELS,
  };
})();
