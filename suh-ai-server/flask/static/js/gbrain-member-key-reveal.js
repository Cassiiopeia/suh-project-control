/* gbrain 팀원 키 결과 창 (#221): 발급 결과 > 다시 보기(관리자 키 재확인 > 남은 초 표시 > 자동 닫힘)
   토큰 카드 결과 창(gbrain-token-result.js)을 재사용, 원문은 그 창 입력칸에만 두고 닫으면 비움
   API: ../gbrain/member-keys/{id}/reveal (POST) */
(function () {
  const { getElement, readResponseBody, describeFailure } = window.gbrainPage;
  const KEY_API = '../gbrain/member-keys';
  // 남은 시간이 이 초 이하면 배지를 경고색 > 오류색으로 바꿈
  const COUNTDOWN_URGENT_SECONDS = 10;
  const COUNTDOWN_TICK_MILLISECONDS = 1000;

  // 다시 보기 자동 닫힘 카운트다운 (창을 닫으면 멈춤)
  let countdownTimer = null;

  /* ---------- 1. 결과 창 ---------- */
  // 토큰 카드 결과 창 + 팀원 키 문구: 받는 사람은 항상 팀원 (개인 브레인 키여도 내 기기용 문구를 쓰지 않음)
  function openResultWindow(responseBody, isReveal) {
    window.gbrainTokenResult.open(responseBody, responseBody.mcp_url, responseBody.mcp_server_name);
    getElement('token-secret-title').textContent = responseBody.token.name + (isReveal ? ' 키 다시 보기' : ' 키를 발급했어요');
    getElement('token-secret-warning').textContent = isReveal
      ? '창이 저절로 닫히면 값도 지워져요. 그 팀원에게만 1:1 로 보내 주세요.'
      : '관제소에 암호화해 보관했어요. 잃어버리면 팀원의 키 목록에서 "다시 보기"로 다시 꺼낼 수 있어요.';
    getElement('token-self-install-summary').textContent = '팀원 컴퓨터에 넣는 값';
    getElement('token-self-install-caution').textContent = '토큰은 비밀번호와 같아요. 그 팀원에게 1:1 로만 전하고, 팀원은 자기 컴퓨터에만 넣어요.';
    getElement('token-secret-close').textContent = '팀원에게 보냈어요, 닫기';
    stopCountdown();
    if (isReveal) startCountdown(responseBody.auto_hide_seconds);
  }

  function startCountdown(totalSeconds) {
    let remainingSeconds = totalSeconds;
    renderCountdown(remainingSeconds);
    getElement('token-secret-countdown').hidden = false;
    countdownTimer = setInterval(function () {
      remainingSeconds -= 1;
      if (remainingSeconds > 0) return renderCountdown(remainingSeconds);
      getElement('token-secret-modal').close();
      showToast(totalSeconds + '초가 지나서 키 창을 닫았어요', 'info');
    }, COUNTDOWN_TICK_MILLISECONDS);
  }

  function renderCountdown(remainingSeconds) {
    const countdown = getElement('token-secret-countdown');
    countdown.className = 'badge badge-sm whitespace-nowrap ml-auto gap-1 ' +
      (remainingSeconds <= COUNTDOWN_URGENT_SECONDS ? 'badge-error' : 'badge-warning');
    getElement('token-secret-countdown-text').textContent = remainingSeconds + '초 뒤 닫혀요';
  }

  function stopCountdown() {
    clearInterval(countdownTimer);
    countdownTimer = null;
    getElement('token-secret-countdown').hidden = true;
  }

  /* ---------- 2. 다시 보기 (관리자 키 재확인) ---------- */
  function openReveal(key) {
    getElement('member-reveal-form').reset();
    getElement('member-reveal-target').textContent = key.token_name;
    getElement('member-reveal-modal').dataset.keyId = key.id;
    getElement('member-reveal-error').hidden = true;
    getElement('member-reveal-modal').showModal();
    getElement('member-reveal-admin-key').focus();
  }

  async function submitReveal(event) {
    event.preventDefault();
    const modal = getElement('member-reveal-modal');
    const adminKeyInput = getElement('member-reveal-admin-key');
    const adminKey = adminKeyInput.value;
    adminKeyInput.value = '';  // 보낸 뒤 입력칸에 남기지 않음
    getElement('member-reveal-submit').disabled = true;
    try {
      const response = await apiFetch(KEY_API + '/' + modal.dataset.keyId + '/reveal',
        { method: 'POST', body: JSON.stringify({ admin_key: adminKey }) });
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '키를 다시 보지 못했어요'));
      modal.close();
      openResultWindow(responseBody, true);
    } catch (error) {
      getElement('member-reveal-error').textContent = error.message;
      getElement('member-reveal-error').hidden = false;
    } finally {
      getElement('member-reveal-submit').disabled = false;
    }
  }

  window.gbrainMemberKeyReveal = {
    open: openReveal,
    showIssued: function (responseBody) { openResultWindow(responseBody, false); },
  };

  document.addEventListener('DOMContentLoaded', function () {
    getElement('member-reveal-form').addEventListener('submit', submitReveal);
    // 결과 창 닫힘 (직접 닫기·자동 닫힘·Esc 공통) > 카운트다운 정지
    getElement('token-secret-modal').addEventListener('close', stopCountdown);
  });
})();
