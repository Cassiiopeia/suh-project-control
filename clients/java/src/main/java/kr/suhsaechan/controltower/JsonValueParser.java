package kr.suhsaechan.controltower;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 의존성 없는 최소 JSON 해석: 응답 본문 > Map·List·String·BigDecimal·Boolean·null
 * 형식이 틀리면 IllegalArgumentException
 */
final class JsonValueParser {

    // 객체·배열 최대 중첩 깊이 (깊은 응답으로 StackOverflowError 방지)
    static final int MAXIMUM_NESTING_DEPTH = 64;
    private static final int UNICODE_ESCAPE_LENGTH = 4;
    private static final int HEX_RADIX = 16;

    private final String text;
    private int position;
    private int nestingDepth;

    private JsonValueParser(String text) {
        this.text = text;
    }

    static Object parse(String text) {
        JsonValueParser parser = new JsonValueParser(text);
        Object value = parser.readValue();
        parser.skipWhitespace();
        if (parser.position != text.length()) {
            throw parser.error("trailing characters");
        }
        return value;
    }

    private Object readValue() {
        skipWhitespace();
        if (position >= text.length()) {
            throw error("unexpected end");
        }
        char current = text.charAt(position);
        return switch (current) {
            case '{' -> readNested(true);
            case '[' -> readNested(false);
            case '"' -> readString();
            case 't' -> readLiteral("true", Boolean.TRUE);
            case 'f' -> readLiteral("false", Boolean.FALSE);
            case 'n' -> readLiteral("null", null);
            default -> readNumber();
        };
    }

    /** 중첩 깊이 확인 > 객체 또는 배열 읽기 */
    private Object readNested(boolean isObject) {
        if (++nestingDepth > MAXIMUM_NESTING_DEPTH) {
            throw error("nesting too deep");
        }
        Object nested = isObject ? readObject() : readArray();
        nestingDepth--;
        return nested;
    }

    private Map<String, Object> readObject() {
        Map<String, Object> object = new LinkedHashMap<>();
        position++;
        skipWhitespace();
        if (consumeIf('}')) {
            return object;
        }
        do {
            skipWhitespace();
            if (position >= text.length() || text.charAt(position) != '"') {
                throw error("expected object key");
            }
            String key = readString();
            skipWhitespace();
            expect(':');
            object.put(key, readValue());
            skipWhitespace();
        } while (consumeIf(','));
        expect('}');
        return object;
    }

    private List<Object> readArray() {
        List<Object> array = new ArrayList<>();
        position++;
        skipWhitespace();
        if (consumeIf(']')) {
            return array;
        }
        do {
            array.add(readValue());
            skipWhitespace();
        } while (consumeIf(','));
        expect(']');
        return array;
    }

    private String readString() {
        StringBuilder output = new StringBuilder();
        position++;
        while (position < text.length()) {
            char current = text.charAt(position++);
            if (current == '"') {
                return output.toString();
            }
            if (current != '\\') {
                output.append(current);
                continue;
            }
            if (position >= text.length()) {
                break;
            }
            char escaped = text.charAt(position++);
            switch (escaped) {
                case '"', '\\', '/' -> output.append(escaped);
                case 'n' -> output.append('\n');
                case 'r' -> output.append('\r');
                case 't' -> output.append('\t');
                case 'b' -> output.append('\b');
                case 'f' -> output.append('\f');
                case 'u' -> output.append(readUnicodeEscape());
                default -> throw error("invalid escape");
            }
        }
        throw error("unterminated string");
    }

    /** 16진 4자리만 허용 (부호 +/- 거부) */
    private char readUnicodeEscape() {
        if (position + UNICODE_ESCAPE_LENGTH > text.length()) {
            throw error("short unicode escape");
        }
        int codeUnit = 0;
        for (int offset = 0; offset < UNICODE_ESCAPE_LENGTH; offset++) {
            int digit = Character.digit(text.charAt(position + offset), HEX_RADIX);
            if (digit < 0) {
                throw error("invalid unicode escape");
            }
            codeUnit = codeUnit * HEX_RADIX + digit;
        }
        position += UNICODE_ESCAPE_LENGTH;
        return (char) codeUnit;
    }

    private Object readLiteral(String literal, Object value) {
        if (!text.startsWith(literal, position)) {
            throw error("invalid literal");
        }
        position += literal.length();
        return value;
    }

    private BigDecimal readNumber() {
        int start = position;
        while (position < text.length() && "+-0123456789.eE".indexOf(text.charAt(position)) >= 0) {
            position++;
        }
        try {
            return new BigDecimal(text.substring(start, position));
        } catch (NumberFormatException invalidNumber) {
            throw error("invalid value");
        }
    }

    private void skipWhitespace() {
        while (position < text.length() && " \t\n\r".indexOf(text.charAt(position)) >= 0) {
            position++;
        }
    }

    private boolean consumeIf(char expected) {
        if (position < text.length() && text.charAt(position) == expected) {
            position++;
            return true;
        }
        return false;
    }

    private void expect(char expected) {
        if (!consumeIf(expected)) {
            throw error("expected '" + expected + "'");
        }
    }

    private IllegalArgumentException error(String reason) {
        return new IllegalArgumentException("invalid json at " + position + " : " + reason);
    }
}
