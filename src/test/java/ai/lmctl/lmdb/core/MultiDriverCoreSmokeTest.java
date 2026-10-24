package ai.lmctl.lmdb.core;

import java.util.List;
import java.util.Properties;

/** Runs the same bounded core checks against SQLite-JDBC and DuckDB. */
public final class MultiDriverCoreSmokeTest {
    private MultiDriverCoreSmokeTest() {}
    public static void main(String[] args) {
        check("sqlite", "jdbc:sqlite::memory:");
        check("duckdb", "jdbc:duckdb:");
        System.out.println("lmdb SQLite/DuckDB core smoke tests: PASS");
    }
    private static void check(String name, String url) {
        try (Database db = Database.connect(url, new Properties())) {
            db.executeScript("CREATE TABLE items(id INTEGER PRIMARY KEY, label VARCHAR(20)); INSERT INTO items VALUES (1,'one'),(2,'two');");
            Database.QueryResult result = db.query("SELECT id,label FROM items ORDER BY id");
            require(result.rows().size() == 2 && "one".equals(result.rows().getFirst().get(1)), name + " query");
            require(!db.tables().rows().isEmpty(), name + " metadata");
            require(!db.snapshot().columns().isEmpty(), name + " snapshot");
            require(db.explain("SELECT 1").isQuery(), name + " explain");
            require(Database.json(result).contains("\"label\""), name + " JSON");
        }
    }
    private static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
}
