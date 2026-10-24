package ai.lmctl.lmdb.core;

import java.util.List;
import java.util.Arrays;

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
        System.out.println("lmdb core smoke tests: PASS");
    }
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
