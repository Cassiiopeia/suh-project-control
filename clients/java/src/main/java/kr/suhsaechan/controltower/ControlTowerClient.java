package kr.suhsaechan.controltower;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * 관제소 이벤트 입구 클라이언트: 본문 조립 > POST /control/events > 결과 변환
 * 스레드 안전 (HttpClient 1개 공유, 상태를 바꾸지 않음), notify·notifyAsync는 예외를 던지지 않음
 */
public final class ControlTowerClient {

    static final String EVENTS_PATH = "/control/events";
    static final String TOKEN_HEADER_NAME = "X-Control-Token";
    static final String CONTENT_TYPE = "application/json; charset=utf-8";
    private static final int HTTP_ACCEPTED = 202;
    // notify 대기 여유: orTimeout 결과가 호출 스레드에 전달되는 시간
    private static final Duration SYNC_WAIT_MARGIN = Duration.ofMillis(500);

    private final ControlTowerOptions options;
    private final URI eventsUri;
    private final HttpClient httpClient;

    public ControlTowerClient(ControlTowerOptions options) {
        if (options == null) {
            throw new IllegalArgumentException("options must not be null");
        }
        this.options = options;
        this.eventsUri = URI.create(options.baseUrl() + EVENTS_PATH);
        // 리다이렉트 차단: 토큰 헤더가 다른 주소로 전달되지 않게 3xx를 그대로 결과로 돌림
        this.httpClient = HttpClient.newBuilder()
                .followRedirects(HttpClient.Redirect.NEVER)
                .connectTimeout(options.timeout())
                .build();
    }

    @Override
    public String toString() {
        // 토큰은 출력하지 않음
        return "ControlTowerClient[project=" + options.project() + ", eventsUrl=" + eventsUri + "]";
    }

    /**
     * 요청 본문 조립 (값이 없는 선택 필드는 생략, 잘못된 입력은 IllegalArgumentException)
     */
    public String buildRequestBody(ControlTowerEvent event) {
        if (event == null || event.kind() == null || event.title() == null || event.severity() == null) {
            throw new IllegalArgumentException("event, kind, title and severity must not be null");
        }
        if (event.hasInvalidField()) {
            throw new IllegalArgumentException("field name and value must not be null");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("project", options.project());
        payload.put("kind", event.kind());
        payload.put("severity", event.severity());
        payload.put("title", event.title());
        putIfPresent(payload, "body", event.body());
        putIfPresent(payload, "url", event.url());
        putIfPresent(payload, "dedupe_key", event.dedupeKey());
        if (event.hasFields()) {
            List<Map<String, Object>> fieldObjects = new ArrayList<>();
            for (ControlTowerEvent.Field field : event.fieldList()) {
                Map<String, Object> fieldObject = new LinkedHashMap<>();
                fieldObject.put("name", field.name());
                fieldObject.put("value", field.value());
                fieldObjects.add(fieldObject);
            }
            payload.put("fields", fieldObjects);
        }
        return EventJsonWriter.write(payload);
    }

    /**
     * 알림 1건 전송: 본문 조립 > POST > 결과 변환 (호출 스레드는 최대 timeout + 여유만큼 대기)
     */
    public NotifyResult notify(ControlTowerEvent event) {
        HttpRequest request;
        try {
            request = buildRequest(event);
        } catch (RuntimeException invalidInput) {
            return NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_INVALID_INPUT);
        }
        CompletableFuture<HttpResponse<byte[]>> sendFuture;
        try {
            sendFuture = httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofByteArray());
        } catch (Exception sendFailure) {
            return toFailureResult(sendFailure);
        }
        long waitMilliseconds = options.timeout().plus(SYNC_WAIT_MARGIN).toMillis();
        try {
            return toResultFuture(sendFuture).get(waitMilliseconds, TimeUnit.MILLISECONDS);
        } catch (InterruptedException interrupted) {
            // 인터럽트 상태 복원 > 전송 취소 > 결과로 돌림
            Thread.currentThread().interrupt();
            sendFuture.cancel(true);
            return NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_CONNECTION);
        } catch (TimeoutException waitTimeout) {
            sendFuture.cancel(true);
            return NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_TIMEOUT);
        } catch (Exception waitFailure) {
            sendFuture.cancel(true);
            return toFailureResult(waitFailure);
        }
    }

    /**
     * 비동기 전송: 즉시 반환, timeout 안에 완료, 실패도 결과로 완료 (예외로 완료되지 않음)
     */
    public CompletableFuture<NotifyResult> notifyAsync(ControlTowerEvent event) {
        HttpRequest request;
        try {
            request = buildRequest(event);
        } catch (RuntimeException invalidInput) {
            return CompletableFuture.completedFuture(
                    NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_INVALID_INPUT));
        }
        try {
            return toResultFuture(httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofByteArray()));
        } catch (Exception sendFailure) {
            return CompletableFuture.completedFuture(toFailureResult(sendFailure));
        }
    }

    /**
     * 전송 future > 결과 future: 응답 본문까지 timeout 전체 상한 (초과 시 전송 취소 > timeout)
     * HttpRequest.timeout은 헤더 수신까지만 적용되므로 orTimeout으로 본문까지 묶음
     */
    private CompletableFuture<NotifyResult> toResultFuture(CompletableFuture<HttpResponse<byte[]>> sendFuture) {
        return sendFuture.copy()
                .orTimeout(options.timeout().toMillis(), TimeUnit.MILLISECONDS)
                .handle((response, sendFailure) -> {
                    if (sendFailure != null) {
                        // 진행 중 교환 중단 (이미 끝났으면 영향 없음)
                        sendFuture.cancel(true);
                        return toFailureResult(sendFailure);
                    }
                    return toResult(response.statusCode(), response.body());
                });
    }

    private HttpRequest buildRequest(ControlTowerEvent event) {
        byte[] requestBody = buildRequestBody(event).getBytes(StandardCharsets.UTF_8);
        // timeout: 요청 전체 상한 (connectTimeout은 연결 단계 상한)
        return HttpRequest.newBuilder(eventsUri)
                .timeout(options.timeout())
                .header("Content-Type", CONTENT_TYPE)
                .header(TOKEN_HEADER_NAME, options.token())
                .POST(HttpRequest.BodyPublishers.ofByteArray(requestBody))
                .build();
    }

    private static void putIfPresent(Map<String, Object> payload, String name, String value) {
        if (value != null) {
            payload.put(name, value);
        }
    }

    /**
     * 전송 예외 > 결과 (시간 초과 timeout, 그 외 connection_error)
     */
    private static NotifyResult toFailureResult(Throwable sendFailure) {
        Throwable cause = sendFailure;
        while ((cause instanceof CompletionException || cause instanceof ExecutionException)
                && cause.getCause() != null) {
            cause = cause.getCause();
        }
        // HttpTimeoutException: 연결·헤더 시간 초과, TimeoutException: orTimeout 전체 상한 초과
        boolean isTimeout = cause instanceof HttpTimeoutException || cause instanceof TimeoutException;
        return NotifyResult.failedBeforeResponse(
                isTimeout ? NotifyResult.ERROR_CODE_TIMEOUT : NotifyResult.ERROR_CODE_CONNECTION);
    }

    /**
     * 상태 코드 + 응답 본문 > NotifyResult (JSON이 아니면 http_<상태>)
     */
    static NotifyResult toResult(int statusCode, byte[] rawBody) {
        Object parsed;
        try {
            parsed = JsonValueParser.parse(new String(rawBody == null ? new byte[0] : rawBody, StandardCharsets.UTF_8));
        } catch (RuntimeException notJson) {
            parsed = null;
        }
        Map<?, ?> responseObject = parsed instanceof Map<?, ?> object ? object : Map.of();
        if (statusCode == HTTP_ACCEPTED) {
            boolean isDeduplicated = Boolean.TRUE.equals(responseObject.get("deduplicated"));
            return new NotifyResult(true, statusCode, null, isDeduplicated);
        }
        Object serverError = responseObject.get("error");
        String errorCode = serverError instanceof String text ? text : "http_" + statusCode;
        return new NotifyResult(false, statusCode, errorCode, false);
    }
}
