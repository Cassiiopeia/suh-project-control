package kr.suhsaechan.controltower;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutionException;

/**
 * 관제소 이벤트 입구 클라이언트: 본문 조립 > POST /control/events > 결과 변환
 * 스레드 안전 (HttpClient 1개 공유, 상태를 바꾸지 않음), notify·notifyAsync는 예외를 던지지 않음
 */
public final class ControlTowerClient {

    static final String EVENTS_PATH = "/control/events";
    static final String TOKEN_HEADER_NAME = "X-Control-Token";
    static final String CONTENT_TYPE = "application/json; charset=utf-8";
    private static final int HTTP_ACCEPTED = 202;

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
     * 알림 1건 전송: 본문 조립 > POST > 결과 변환 (호출 스레드에서 응답까지 대기)
     */
    public NotifyResult notify(ControlTowerEvent event) {
        HttpRequest request;
        try {
            request = buildRequest(event);
        } catch (RuntimeException invalidInput) {
            return NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_INVALID_INPUT);
        }
        try {
            HttpResponse<byte[]> response = httpClient.send(request, HttpResponse.BodyHandlers.ofByteArray());
            return toResult(response.statusCode(), response.body());
        } catch (InterruptedException interrupted) {
            // 인터럽트 상태 복원 후 결과로 돌림
            Thread.currentThread().interrupt();
            return NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_CONNECTION);
        } catch (Exception sendFailure) {
            return toFailureResult(sendFailure);
        }
    }

    /**
     * 비동기 전송: 즉시 반환, 실패도 결과로 완료 (예외로 완료되지 않음)
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
            return httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofByteArray())
                    .handle((response, sendFailure) -> sendFailure == null
                            ? toResult(response.statusCode(), response.body())
                            : toFailureResult(sendFailure));
        } catch (Exception sendFailure) {
            return CompletableFuture.completedFuture(toFailureResult(sendFailure));
        }
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
        // HttpConnectTimeoutException도 HttpTimeoutException 하위
        boolean isTimeout = cause instanceof HttpTimeoutException;
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
