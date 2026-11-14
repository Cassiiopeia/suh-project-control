package kr.suhsaechan.controltower;

/**
 * 전송 결과: 접수 여부, HTTP 상태, 실패 코드, 중복 억제 여부 (예외 대신 결과로 돌려줌)
 *
 * @param isAccepted     서버가 접수(202)했는지
 * @param statusCode     HTTP 상태 코드 (네트워크 오류·시간 초과·init 전·로컬 검증 실패는 null)
 * @param errorCode      실패 코드: 서버 error 값 | http_&lt;상태&gt; | timeout | connection_error | not_initialized | invalid_input
 * @param isDeduplicated dedupe_key 중복으로 알림 없이 접수만 됐는지
 */
public record NotifyResult(boolean isAccepted, Integer statusCode, String errorCode, boolean isDeduplicated) {

    public static final String ERROR_CODE_TIMEOUT = "timeout";
    public static final String ERROR_CODE_CONNECTION = "connection_error";
    public static final String ERROR_CODE_NOT_INITIALIZED = "not_initialized";
    // 보내기 전 로컬 검증 실패 (서버의 invalid와 구분)
    public static final String ERROR_CODE_INVALID_INPUT = "invalid_input";

    /** 요청 전 실패 (상태 코드 없음) */
    static NotifyResult failedBeforeResponse(String errorCode) {
        return new NotifyResult(false, null, errorCode, false);
    }
}
