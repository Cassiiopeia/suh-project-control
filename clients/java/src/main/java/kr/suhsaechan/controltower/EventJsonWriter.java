package kr.suhsaechan.controltower;

import java.util.Iterator;
import java.util.List;
import java.util.Map;

/**
 * 의존성 없는 JSON 작성: Map(순서 유지), List, String, Boolean, Number, null > JSON 문자열
 * 이스케이프: 따옴표, 역슬래시, 제어문자(U+0000~001F), U+2028/2029 (한글·이모지는 그대로)
 */
final class EventJsonWriter {

    private static final char LAST_CONTROL_CHARACTER = 0x1F;
    private static final char LINE_SEPARATOR = '\u2028';
    private static final char PARAGRAPH_SEPARATOR = '\u2029';

    private EventJsonWriter() {
    }

    static String write(Object jsonValue) {
        StringBuilder output = new StringBuilder();
        appendValue(output, jsonValue);
        return output.toString();
    }

    private static void appendValue(StringBuilder output, Object jsonValue) {
        if (jsonValue == null) {
            output.append("null");
        } else if (jsonValue instanceof String text) {
            appendString(output, text);
        } else if (jsonValue instanceof Boolean || jsonValue instanceof Number) {
            output.append(jsonValue);
        } else if (jsonValue instanceof Map<?, ?> object) {
            appendObject(output, object);
        } else if (jsonValue instanceof List<?> array) {
            appendArray(output, array);
        } else {
            throw new IllegalArgumentException("unsupported json value type: " + jsonValue.getClass().getName());
        }
    }

    private static void appendObject(StringBuilder output, Map<?, ?> object) {
        output.append('{');
        Iterator<? extends Map.Entry<?, ?>> entries = object.entrySet().iterator();
        while (entries.hasNext()) {
            Map.Entry<?, ?> entry = entries.next();
            appendString(output, String.valueOf(entry.getKey()));
            output.append(':');
            appendValue(output, entry.getValue());
            if (entries.hasNext()) {
                output.append(',');
            }
        }
        output.append('}');
    }

    private static void appendArray(StringBuilder output, List<?> array) {
        output.append('[');
        for (int index = 0; index < array.size(); index++) {
            if (index > 0) {
                output.append(',');
            }
            appendValue(output, array.get(index));
        }
        output.append(']');
    }

    /**
     * 문자열 이스케이프 (짝 없는 서로게이트는 UTF-8로 못 보내므로 IllegalArgumentException)
     */
    private static void appendString(StringBuilder output, String text) {
        output.append('"');
        for (int index = 0; index < text.length(); index++) {
            char character = text.charAt(index);
            switch (character) {
                case '"' -> output.append("\\\"");
                case '\\' -> output.append("\\\\");
                case '\n' -> output.append("\\n");
                case '\r' -> output.append("\\r");
                case '\t' -> output.append("\\t");
                case '\b' -> output.append("\\b");
                case '\f' -> output.append("\\f");
                default -> index = appendOtherCharacter(output, text, index, character);
            }
        }
        output.append('"');
    }

    /** 제어문자·줄 구분자 > 유니코드 이스케이프 4자리, 서로게이트 쌍 > 그대로 (처리한 마지막 위치 반환) */
    private static int appendOtherCharacter(StringBuilder output, String text, int index, char character) {
        if (character <= LAST_CONTROL_CHARACTER || character == LINE_SEPARATOR || character == PARAGRAPH_SEPARATOR) {
            output.append(String.format("\\u%04x", (int) character));
            return index;
        }
        if (Character.isHighSurrogate(character)) {
            boolean hasLowSurrogate = index + 1 < text.length() && Character.isLowSurrogate(text.charAt(index + 1));
            if (!hasLowSurrogate) {
                throw new IllegalArgumentException("unpaired surrogate in string");
            }
            output.append(character).append(text.charAt(index + 1));
            return index + 1;
        }
        if (Character.isLowSurrogate(character)) {
            throw new IllegalArgumentException("unpaired surrogate in string");
        }
        output.append(character);
        return index;
    }
}
