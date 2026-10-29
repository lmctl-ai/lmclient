package ai.lmctl.lmclient.core;

import java.util.ArrayList;
import java.util.List;

/** SQL splitter which respects quoted strings, identifiers, comments, and PostgreSQL dollar quotes. */
public final class SqlScript {
    private SqlScript() {}
    public static List<String> split(String script) {
        if (script == null || script.isBlank()) return List.of();
        List<String> result = new ArrayList<>();
        StringBuilder out = new StringBuilder();
        char quote = 0; boolean lineComment = false; int blockDepth = 0;
        String dollar = null;
        for (int i = 0; i < script.length(); i++) {
            char c = script.charAt(i), next = i + 1 < script.length() ? script.charAt(i + 1) : 0;
            if (lineComment) { if (c == '\n') { lineComment = false; out.append('\n'); } else continue; }
            else if (blockDepth > 0) {
                if (c == '/' && next == '*') { blockDepth++; i++; }
                else if (c == '*' && next == '/') { blockDepth--; i++; }
                continue;
            }
            else if (dollar != null) {
                if (script.startsWith(dollar, i)) { out.append(dollar); i += dollar.length() - 1; dollar = null; }
                else out.append(c);
            } else if (quote != 0) {
                out.append(c);
                if (c == quote) {
                    if (next == quote) { out.append(next); i++; }
                    else quote = 0;
                }
            } else if (c == '-' && next == '-') { ensureSeparator(out); lineComment = true; i++; }
            else if (c == '/' && next == '*') { ensureSeparator(out); blockDepth = 1; i++; }
            else if (c == '\'' || c == '"' || c == '`' || c == '[') { quote = c == '[' ? ']' : c; out.append(c); }
            else if (c == '$') {
                int end = script.indexOf('$', i + 1);
                if (end == i + 1 || (end > i && script.substring(i + 1, end).matches("[A-Za-z_][A-Za-z0-9_]*"))) {
                    dollar = script.substring(i, end + 1); out.append(dollar); i = end;
                } else out.append(c);
            } else if (c == ';') { add(result, out); }
            else out.append(c);
        }
        if (quote != 0 || dollar != null || blockDepth > 0) throw new IllegalArgumentException("unterminated SQL quote or comment");
        add(result, out); return List.copyOf(result);
    }
    private static void ensureSeparator(StringBuilder out) {
        if (out.length() > 0 && !Character.isWhitespace(out.charAt(out.length() - 1))) out.append(' ');
    }
    private static void add(List<String> result, StringBuilder out) {
        String value = out.toString().trim(); out.setLength(0);
        if (!value.isEmpty()) result.add(value);
    }
}
