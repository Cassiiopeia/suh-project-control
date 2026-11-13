package kr.suhsaechan.controltower;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * 보낼 알림 1건: kind, title(필수) + fields, body, url, severity, dedupeKey(선택)
 * 잘못된 입력(null 필드 이름·값)은 예외 없이 기록 > notify 시 invalid_input
 */
public final class ControlTowerEvent {

    public static final String DEFAULT_SEVERITY = "info";

    /** 필드 1개 (이름, 문자열 값) */
    record Field(String name, String value) {
    }

    private final String kind;
    private final String title;
    private final List<Field> fields = new ArrayList<>();
    private boolean hasFields;
    private boolean hasInvalidField;
    private String body;
    private String url;
    private String severity = DEFAULT_SEVERITY;
    private String dedupeKey;

    private ControlTowerEvent(String kind, String title) {
        this.kind = kind;
        this.title = title;
    }

    public static ControlTowerEvent of(String kind, String title) {
        return new ControlTowerEvent(kind, title);
    }

    /** 필드 1개 추가 (넣은 순서 유지, 값은 String.valueOf로 문자열화) */
    public ControlTowerEvent field(String name, Object value) {
        hasFields = true;
        if (name == null || value == null) {
            hasInvalidField = true;
            return this;
        }
        fields.add(new Field(name, String.valueOf(value)));
        return this;
    }

    /** 필드 여러 개 추가 (Map 순회 순서 유지: LinkedHashMap 권장, 빈 Map > "fields": []) */
    public ControlTowerEvent fields(Map<String, ?> namedValues) {
        if (namedValues == null) {
            return this;
        }
        hasFields = true;
        namedValues.forEach(this::field);
        return this;
    }

    public ControlTowerEvent body(String body) {
        this.body = body;
        return this;
    }

    public ControlTowerEvent url(String url) {
        this.url = url;
        return this;
    }

    public ControlTowerEvent severity(String severity) {
        this.severity = severity;
        return this;
    }

    public ControlTowerEvent dedupeKey(String dedupeKey) {
        this.dedupeKey = dedupeKey;
        return this;
    }

    String kind() {
        return kind;
    }

    String title() {
        return title;
    }

    List<Field> fieldList() {
        return Collections.unmodifiableList(fields);
    }

    boolean hasFields() {
        return hasFields;
    }

    boolean hasInvalidField() {
        return hasInvalidField;
    }

    String body() {
        return body;
    }

    String url() {
        return url;
    }

    String severity() {
        return severity;
    }

    String dedupeKey() {
        return dedupeKey;
    }
}
