package ai.lmctl.lmclient.core;

import java.util.List;

final class ResultFormats {
    private ResultFormats() {}
    static String csv(Database.QueryResult result) {
        if (!result.isQuery()) return "update_count\n" + result.updateCount() + "\n";
        StringBuilder b = new StringBuilder(); row(b, result.columns());
        for (List<Object> values : result.rows()) row(b, values);
        return b.toString();
    }
    private static void row(StringBuilder b, List<?> values) {
        for (int i = 0; i < values.size(); i++) { if (i != 0) b.append(','); b.append(csvCell(values.get(i))); }
        b.append('\n');
    }
    private static String csvCell(Object value) {
        if (value instanceof byte[] bytes) return java.util.HexFormat.of().formatHex(bytes);
        String s = value == null ? "" : String.valueOf(value);
        return s.indexOf(',') >= 0 || s.indexOf('"') >= 0 || s.indexOf('\n') >= 0 || s.indexOf('\r') >= 0
                ? "\"" + s.replace("\"", "\"\"") + "\"" : s;
    }
    static String json(Database.QueryResult result) {
        if (!result.isQuery()) return "[{\"update_count\": " + result.updateCount() + "}]\n";
        java.util.Set<String> labels = new java.util.HashSet<>();
        for (String column : result.columns()) if (!labels.add(column)) throw new IllegalArgumentException("JSON export requires unique column labels");
        StringBuilder b = new StringBuilder("[\n");
        for (int r = 0; r < result.rows().size(); r++) {
            if (r != 0) b.append(",\n"); b.append("  {");
            List<Object> row = result.rows().get(r);
            for (int c = 0; c < result.columns().size(); c++) {
                if (c != 0) b.append(','); b.append('\n').append("    ").append(quote(result.columns().get(c))).append(": ").append(value(row.get(c)));
            }
            if (!row.isEmpty()) b.append('\n').append("  "); b.append('}');
        }
        return b.append("\n]\n").toString();
    }
    private static String value(Object v) {
        if (v == null) return "null";
        if (v instanceof Double d && !Double.isFinite(d) || v instanceof Float f && !Float.isFinite(f)) return "null";
        if (v instanceof Number || v instanceof Boolean) return String.valueOf(v);
        if (v instanceof byte[] bytes) return quote(java.util.HexFormat.of().formatHex(bytes));
        return quote(String.valueOf(v));
    }
    /** JSON strings escape every control code point; non-finite numbers are emitted as null. */
    private static String quote(String s) {
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\' -> out.append("\\\\"); case '"' -> out.append("\\\"");
                case '\b' -> out.append("\\b"); case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n"); case '\r' -> out.append("\\r"); case '\t' -> out.append("\\t");
                default -> { if (c < 0x20) out.append(String.format("\\u%04x", (int)c)); else out.append(c); }
            }
        }
        return out.append('"').toString();
    }
    static String table(Database.QueryResult result) {
        if (!result.isQuery()) return "+--------------+\n| update_count |\n+--------------+\n| " + String.format("%-12s", result.updateCount()) + " |\n+--------------+\n";
        int n = result.columns().size(); int[] widths = new int[n];
        for (int i = 0; i < n; i++) widths[i] = result.columns().get(i).length();
        for (List<Object> row : result.rows()) for (int i = 0; i < n; i++) widths[i] = Math.min(80, Math.max(widths[i], String.valueOf(row.get(i)).length()));
        StringBuilder b = new StringBuilder(); separator(b, widths); line(b, result.columns(), widths); separator(b, widths);
        for (List<Object> row : result.rows()) line(b, row, widths); separator(b, widths); return b.toString();
    }
    private static void separator(StringBuilder b, int[] widths) { b.append('+'); for (int w : widths) b.append("-".repeat(w + 2)).append('+'); b.append('\n'); }
    private static void line(StringBuilder b, List<?> row, int[] widths) { b.append('|'); for (int i = 0; i < widths.length; i++) { String s = String.valueOf(row.get(i)); if (s.length() > widths[i]) s = s.substring(0, widths[i]); b.append(' ').append(String.format("%-" + widths[i] + "s", s)).append(" |"); } b.append('\n'); }
}
