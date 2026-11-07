/**
 * HTTP 공통: JSON·텍스트 응답 생성, 응답 본문 취소
 */

export function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });
}

export function textResponse(text, status = 200) {
  return new Response(text, { status, headers: { 'content-type': 'text/plain; charset=utf-8' } });
}

/** 본문 미수신: 스트림 취소 (실패는 무시) */
export function cancelBody(response) {
  try {
    response?.body?.cancel?.()?.catch?.(() => {});
  } catch {
    // 이미 잠긴 스트림 등: 결과에 영향 없음
  }
}
