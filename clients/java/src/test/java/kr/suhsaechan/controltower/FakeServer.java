package kr.suhsaechan.controltower;

import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * 테스트 서버 (127.0.0.1): 응답 상태·본문·지연·추가 헤더 지정, 받은 요청 기록
 */
final class FakeServer implements AutoCloseable {

    /** 받은 요청 1건: 경로, 헤더, 본문 바이트 */
    record ReceivedRequest(String path, Headers headers, byte[] body) {
        String bodyText() {
            return new String(body, StandardCharsets.UTF_8);
        }
    }

    static final String DEFAULT_RESPONSE_BODY = "{\"accepted\": true, \"deduplicated\": false}";

    final List<ReceivedRequest> receivedRequests = new CopyOnWriteArrayList<>();
    final Map<String, String> extraHeaders = new ConcurrentHashMap<>();
    private final HttpServer httpServer;
    private final ExecutorService handlerExecutor = Executors.newCachedThreadPool();
    private volatile int status = 202;
    private volatile byte[] responseBody = DEFAULT_RESPONSE_BODY.getBytes(StandardCharsets.UTF_8);
    private volatile long delayMilliseconds = 0;
    // 지정하면 응답 전에 이 래치가 풀릴 때까지 대기
    private volatile CountDownLatch responseGate;
    // 0보다 크면 헤더와 본문 일부만 보낸 뒤 이 시간만큼 멈춤 (본문 지연)
    private volatile long bodyStallMilliseconds = 0;

    FakeServer() throws IOException {
        httpServer = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        httpServer.setExecutor(handlerExecutor);
        httpServer.createContext("/", this::handle);
        httpServer.start();
    }

    FakeServer respond(int status, String responseBody) {
        this.status = status;
        this.responseBody = responseBody.getBytes(StandardCharsets.UTF_8);
        return this;
    }

    FakeServer delay(long delayMilliseconds) {
        this.delayMilliseconds = delayMilliseconds;
        return this;
    }

    FakeServer stallBodyAfterHeaders(long bodyStallMilliseconds) {
        this.bodyStallMilliseconds = bodyStallMilliseconds;
        return this;
    }

    FakeServer holdResponsesUntil(CountDownLatch responseGate) {
        this.responseGate = responseGate;
        return this;
    }

    String baseUrl() {
        return "http://127.0.0.1:" + httpServer.getAddress().getPort();
    }

    private void handle(HttpExchange exchange) throws IOException {
        // 요청 기록 > (대기) > 응답
        byte[] requestBody = exchange.getRequestBody().readAllBytes();
        receivedRequests.add(new ReceivedRequest(exchange.getRequestURI().getPath(),
                exchange.getRequestHeaders(), requestBody));
        try {
            CountDownLatch gate = responseGate;
            if (gate != null) {
                gate.await(5, TimeUnit.SECONDS);
            }
            Thread.sleep(delayMilliseconds);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        try {
            extraHeaders.forEach((name, value) -> exchange.getResponseHeaders().add(name, value));
            exchange.sendResponseHeaders(status, responseBody.length == 0 ? -1 : responseBody.length);
            try (OutputStream output = exchange.getResponseBody()) {
                writeBody(output);
            }
        } catch (IOException clientGone) {
            // 클라이언트가 시간 초과로 먼저 끊은 경우
        } finally {
            exchange.close();
        }
    }

    /** 본문 쓰기 (본문 지연 모드: 첫 바이트 > 멈춤 > 나머지) */
    private void writeBody(OutputStream output) throws IOException {
        if (bodyStallMilliseconds <= 0 || responseBody.length < 2) {
            output.write(responseBody);
            return;
        }
        output.write(responseBody, 0, 1);
        output.flush();
        try {
            Thread.sleep(bodyStallMilliseconds);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return;
        }
        output.write(responseBody, 1, responseBody.length - 1);
    }

    @Override
    public void close() {
        httpServer.stop(0);
        // 멈춘 핸들러 스레드까지 정리
        handlerExecutor.shutdownNow();
    }
}
