package kr.suhsaechan.controltower;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 클라이언트 동작 테스트: 로컬 127.0.0.1 HttpServer만 사용
 */
class ControlTowerClientTest {

    private static final String TOKEN = "secret-token-123";
    private final List<FakeServer> servers = new ArrayList<>();

    @AfterEach
    void closeServers() {
        servers.forEach(FakeServer::close);
    }

    private FakeServer startServer() throws IOException {
        FakeServer server = new FakeServer();
        servers.add(server);
        return server;
    }

    private static ControlTowerClient makeClient(String baseUrl, Duration timeout) {
        return new ControlTowerClient(ControlTowerOptions.builder()
                .baseUrl(baseUrl).project("suh-ai").token(TOKEN).timeout(timeout).build());
    }

    private static ControlTowerClient makeClient(FakeServer server) {
        return makeClient(server.baseUrl(), Duration.ofSeconds(3));
    }

    @Test
    void accepted() throws IOException {
        FakeServer server = startServer();
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("report", "제목"));
        assertEquals(new NotifyResult(true, 202, null, false), result);
        assertEquals("/control/events", server.receivedRequests.get(0).path());
    }

    @Test
    void deduplicated() throws IOException {
        FakeServer server = startServer().respond(202, "{\"accepted\": true, \"deduplicated\": true}");
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("report", "제목").dedupeKey("k"));
        assertTrue(result.isAccepted());
        assertTrue(result.isDeduplicated());
    }

    @Test
    void unknownKind() throws IOException {
        FakeServer server = startServer().respond(400, "{\"error\": \"unknown_kind\", \"kind\": \"x\"}");
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("x", "제목"));
        assertEquals(new NotifyResult(false, 400, "unknown_kind", false), result);
    }

    @ParameterizedTest
    @CsvSource({"401,unauthorized", "404,unknown_project", "503,unavailable", "400,invalid"})
    void serverErrorCodes(int status, String errorCode) throws IOException {
        FakeServer server = startServer().respond(status, "{\"error\": \"" + errorCode + "\"}");
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("report", "제목"));
        assertEquals(new NotifyResult(false, status, errorCode, false), result);
    }

    @Test
    void non202SuccessIsNotAccepted() throws IOException {
        FakeServer server = startServer().respond(200, "{\"accepted\": true}");
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("report", "제목"));
        assertFalse(result.isAccepted());
        assertEquals(200, result.statusCode());
    }

    @Test
    void redirectNotFollowedAndTokenNotForwarded() throws IOException {
        FakeServer target = startServer();
        FakeServer redirector = startServer().respond(302, FakeServer.DEFAULT_RESPONSE_BODY);
        redirector.extraHeaders.put("Location", target.baseUrl() + "/control/events");
        NotifyResult result = makeClient(redirector).notify(ControlTowerEvent.of("report", "제목"));
        assertEquals(new NotifyResult(false, 302, "http_302", false), result);
        assertTrue(target.receivedRequests.isEmpty());
    }

    @Test
    void nullFieldValueIsInvalidInputAndNotSent() throws IOException {
        FakeServer server = startServer();
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("report", "t").field("a", null));
        assertEquals(new NotifyResult(false, null, "invalid_input", false), result);
        assertTrue(server.receivedRequests.isEmpty());
    }

    @Test
    void nullFieldNameIsInvalidInputAndNotSent() throws IOException {
        FakeServer server = startServer();
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put(null, "v");
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("report", "t").fields(fields));
        assertEquals("invalid_input", result.errorCode());
        assertTrue(server.receivedRequests.isEmpty());
    }

    @Test
    void nullEventIsInvalidInput() throws IOException {
        FakeServer server = startServer();
        assertEquals("invalid_input", makeClient(server).notify(null).errorCode());
        assertEquals("invalid_input", makeClient(server).notifyAsync(null).join().errorCode());
        assertTrue(server.receivedRequests.isEmpty());
    }

    @Test
    void nonJsonErrorUsesHttpStatus() throws IOException {
        FakeServer server = startServer().respond(413, "<html>too large</html>");
        NotifyResult result = makeClient(server).notify(ControlTowerEvent.of("report", "제목"));
        assertEquals(new NotifyResult(false, 413, "http_413", false), result);
    }

    @Test
    void timeout() throws IOException {
        FakeServer server = startServer().delay(1000);
        NotifyResult result = makeClient(server.baseUrl(), Duration.ofMillis(200))
                .notify(ControlTowerEvent.of("report", "제목"));
        assertEquals(new NotifyResult(false, null, "timeout", false), result);
    }

    @Test
    void connectionRefused() {
        NotifyResult result = makeClient("http://127.0.0.1:1", Duration.ofSeconds(1))
                .notify(ControlTowerEvent.of("report", "제목"));
        assertEquals(new NotifyResult(false, null, "connection_error", false), result);
    }

    @Test
    void koreanBodySentAsUtf8WithHeaders() throws IOException {
        FakeServer server = startServer();
        makeClient(server).notify(ControlTowerEvent.of("report", "한글 제목")
                .body("본문").field("요청 경로", "메일 링크").url("https://a.b"));
        FakeServer.ReceivedRequest request = server.receivedRequests.get(0);
        String expectedTitle = new String("한글 제목".getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8);
        assertTrue(request.bodyText().contains(expectedTitle));
        assertEquals(TOKEN, request.headers().getFirst("X-Control-Token"));
        assertEquals("application/json; charset=utf-8", request.headers().getFirst("Content-Type"));
        Map<?, ?> payload = (Map<?, ?>) JsonValueParser.parse(request.bodyText());
        assertEquals(List.of(Map.of("name", "요청 경로", "value", "메일 링크")), payload.get("fields"));
    }

    @Test
    void fieldsKeepInsertionOrderAndStringifyValues() throws IOException {
        FakeServer server = startServer();
        makeClient(server).notify(ControlTowerEvent.of("report", "t").field("b", "1").field("a", 2));
        Map<?, ?> payload = (Map<?, ?>) JsonValueParser.parse(server.receivedRequests.get(0).bodyText());
        assertEquals(List.of(Map.of("name", "b", "value", "1"), Map.of("name", "a", "value", "2")),
                payload.get("fields"));
    }

    @Test
    void optionalFieldsOmitted() throws IOException {
        FakeServer server = startServer();
        makeClient(server).notify(ControlTowerEvent.of("report", "t"));
        assertEquals(Map.of("project", "suh-ai", "kind", "report", "severity", "info", "title", "t"),
                JsonValueParser.parse(server.receivedRequests.get(0).bodyText()));
    }

    @Test
    void toStringHasNoToken() throws IOException {
        FakeServer server = startServer();
        ControlTowerClient client = makeClient(server);
        assertFalse(client.toString().contains(TOKEN));
        assertTrue(client.toString().contains("suh-ai"));
    }

    @Test
    void notifyAsyncReturnsBeforeResponse() throws Exception {
        CountDownLatch releaseResponse = new CountDownLatch(1);
        FakeServer server = startServer().holdResponsesUntil(releaseResponse);
        CompletableFuture<NotifyResult> future = makeClient(server.baseUrl(), Duration.ofSeconds(10))
                .notifyAsync(ControlTowerEvent.of("report", "t"));
        // 서버가 응답을 막고 있는 동안에도 호출이 반환됐고 전송은 아직 끝나지 않음
        assertFalse(future.isDone());
        releaseResponse.countDown();
        assertTrue(future.get(5, TimeUnit.SECONDS).isAccepted());
        assertEquals(1, server.receivedRequests.size());
    }

    @Test
    void notifyAsyncFailureCompletesNormally() {
        NotifyResult result = makeClient("http://127.0.0.1:1", Duration.ofSeconds(1))
                .notifyAsync(ControlTowerEvent.of("report", "t")).join();
        assertEquals("connection_error", result.errorCode());
        assertNull(result.statusCode());
    }

    @Test
    void notifyAsyncTimeoutCompletesNormally() throws IOException {
        FakeServer server = startServer().delay(1000);
        NotifyResult result = makeClient(server.baseUrl(), Duration.ofMillis(200))
                .notifyAsync(ControlTowerEvent.of("report", "t")).join();
        assertEquals("timeout", result.errorCode());
    }
}
