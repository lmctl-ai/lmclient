package ai.lmctl.lmclient.core;

import java.util.List;
import java.util.Arrays;
import java.sql.SQLException;

/** Dependency-free smoke test; run with {@code java ...CoreSmokeTest}. */
public final class CoreSmokeTest {
    private CoreSmokeTest() {}
    public static void main(String[] args) {
        List<String> statements = SqlScript.split("-- comment;\nCREATE TABLE t(a text); INSERT INTO t VALUES ('x;y'); /* ; */ SELECT 'it''s';");
        check(statements.size() == 3, "SQL splitter statement count");
        check(statements.get(1).contains("x;y"), "SQL splitter quoted semicolon");
        check(SqlScript.split("SELECT/* keep tokens */1; SELECT [x;y] FROM t; SELECT $$a;b$$;").size() == 3, "SQL dialect quoting");
        check(SqlScript.split("SELECT/* outer /* nested */ comment */1").getFirst().equals("SELECT 1"), "nested comment separator");
        Database.QueryResult result = new Database.QueryResult(List.of("a", "b"), List.of(Arrays.asList("x,y", 2), Arrays.asList(null, true)), -1);
        check(ResultFormats.csv(result).equals("a,b\nx,y,2\n,true\n".replace("x,y,2", "\"x,y\",2")), "CSV escaping");
        check(ResultFormats.json(result).contains("\"a\": \"x,y\""), "JSON rendering");
        check(ResultFormats.table(result).contains("| a"), "table rendering");
        var controls = new Database.QueryResult(List.of("text", "bytes"), List.of(Arrays.asList("a\b\f\u0000", new byte[]{0, 15})), -1);
        String controlJson = ResultFormats.json(controls);
        check(controlJson.contains("\\b") && controlJson.contains("\\f") && controlJson.contains("\\u0000"), "JSON controls");
        check(ResultFormats.csv(controls).contains("000f"), "CSV bytes");
        check(ResultFormats.json(new Database.QueryResult(List.of(), List.of(), 3)).contains("update_count"), "DML JSON");
        boolean duplicate = false;
        try { ResultFormats.json(new Database.QueryResult(List.of("x", "x"), List.of(Arrays.asList(1, 2)), -1)); } catch (IllegalArgumentException expected) { duplicate = true; }
        check(duplicate, "duplicate JSON labels");
        String safeError = DatabaseException.from(new SQLException("jdbc:postgresql://user:secret@example/db password=secret", "08001")).getMessage();
        check(!safeError.contains("postgresql") && !safeError.contains("secret"), "SQL error redaction");
        System.out.println("lmclient core smoke tests: PASS");
    }
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
