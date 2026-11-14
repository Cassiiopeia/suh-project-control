package kr.suhsaechan.controltower;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.Duration;
import java.util.Locale;
import java.util.Set;

/**
 * 클라이언트 설정: project, token(필수), baseUrl, timeout
 * build() 시점 검증 > 잘못되면 IllegalArgumentException (토큰 값은 메시지에 넣지 않음)
 */
public final class ControlTowerOptions {

    public static final String DEFAULT_BASE_URL = "https://ai.suhsaechan.kr/api/flask";
    // 요청 전체 시간 상한 (연결 + 응답 대기)
    public static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(3);
    // 평문 http를 허용하는 호스트 (로컬 테스트 전용)
    private static final Set<String> PLAINTEXT_ALLOWED_HOSTS = Set.of("127.0.0.1", "localhost");
    // 토큰 허용 문자 범위: ASCII 인쇄 가능, 공백 제외 (헤더 값으로 안전)
    private static final char TOKEN_FIRST_ALLOWED_CHARACTER = 0x21;
    private static final char TOKEN_LAST_ALLOWED_CHARACTER = 0x7E;

    private final String project;
    private final String token;
    private final String baseUrl;
    private final Duration timeout;

    private ControlTowerOptions(Builder builder) {
        validate(builder);
        this.project = builder.project;
        this.token = builder.token;
        this.baseUrl = stripTrailingSlashes(builder.baseUrl);
        this.timeout = builder.timeout;
    }

    public static Builder builder() {
        return new Builder();
    }

    public String project() {
        return project;
    }

    // 클라이언트 내부 전용 (공개 getter 없음)
    String token() {
        return token;
    }

    public String baseUrl() {
        return baseUrl;
    }

    public Duration timeout() {
        return timeout;
    }

    @Override
    public String toString() {
        // 토큰은 출력하지 않음
        return "ControlTowerOptions[project=" + project + ", baseUrl=" + baseUrl + ", timeout=" + timeout + "]";
    }

    /**
     * 설정 검증 (project, token, baseUrl, timeout)
     */
    private static void validate(Builder builder) {
        if (builder.project == null || builder.project.isEmpty()) {
            throw new IllegalArgumentException("project must be a non-empty string");
        }
        if (builder.token == null || builder.token.isEmpty()) {
            throw new IllegalArgumentException("token must be a non-empty string");
        }
        if (!hasOnlyHeaderSafeCharacters(builder.token)) {
            throw new IllegalArgumentException("token must not contain whitespace, control or non-ASCII characters");
        }
        if (!isAllowedBaseUrl(builder.baseUrl)) {
            throw new IllegalArgumentException("baseUrl must be https (http only for 127.0.0.1 or localhost)");
        }
        if (builder.timeout == null || builder.timeout.isZero() || builder.timeout.isNegative()) {
            throw new IllegalArgumentException("timeout must be a positive duration");
        }
    }

    private static boolean hasOnlyHeaderSafeCharacters(String token) {
        return token.chars().allMatch(character ->
                character >= TOKEN_FIRST_ALLOWED_CHARACTER && character <= TOKEN_LAST_ALLOWED_CHARACTER);
    }

    private static boolean isAllowedBaseUrl(String baseUrl) {
        if (baseUrl == null) {
            return false;
        }
        URI uri;
        try {
            uri = new URI(baseUrl);
        } catch (URISyntaxException invalidUri) {
            return false;
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost() == null ? null : uri.getHost().toLowerCase(Locale.ROOT);
        boolean isHttps = scheme.equals("https") && host != null && !host.isEmpty();
        boolean isLocalHttp = scheme.equals("http") && host != null && PLAINTEXT_ALLOWED_HOSTS.contains(host);
        return isHttps || isLocalHttp;
    }

    private static String stripTrailingSlashes(String baseUrl) {
        int end = baseUrl.length();
        while (end > 0 && baseUrl.charAt(end - 1) == '/') {
            end--;
        }
        return baseUrl.substring(0, end);
    }

    /**
     * 설정 빌더: project, token 필수 (나머지는 기본값)
     */
    public static final class Builder {
        private String project;
        private String token;
        private String baseUrl = DEFAULT_BASE_URL;
        private Duration timeout = DEFAULT_TIMEOUT;

        private Builder() {
        }

        public Builder project(String project) {
            this.project = project;
            return this;
        }

        public Builder token(String token) {
            this.token = token;
            return this;
        }

        public Builder baseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
            return this;
        }

        public Builder timeout(Duration timeout) {
            this.timeout = timeout;
            return this;
        }

        public ControlTowerOptions build() {
            return new ControlTowerOptions(this);
        }

        @Override
        public String toString() {
            // 토큰은 출력하지 않음
            return "ControlTowerOptions.Builder[project=" + project + ", baseUrl=" + baseUrl + "]";
        }
    }
}
