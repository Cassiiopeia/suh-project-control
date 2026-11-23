/* gbrain 관리 화면 공통 (#213): 요소 찾기, 응답 본문 읽기, 실패 문구 + 에러 코드
   사용처 4개: gbrain.js, gbrain-tokens.js, gbrain-token-result.js, gbrain-teams.js (이 파일을 먼저 로드) */
window.gbrainPage = (function () {
  function getElement(id) { return document.getElementById(id); }

  // JSON 이 아니거나 비어 있으면 빈 객체 (실패 응답도 문구를 만들 수 있게)
  async function readResponseBody(response) {
    try { return await response.json(); } catch (error) { return {}; }
  }

  // 실패 문구 + 에러 코드 (화면 문구 규칙: 오류에는 코드 함께)
  function describeFailure(responseBody, fallbackMessage) {
    return (responseBody.error || fallbackMessage) + (responseBody.code ? ' [' + responseBody.code + ']' : '');
  }

  return { getElement: getElement, readResponseBody: readResponseBody, describeFailure: describeFailure };
})();
