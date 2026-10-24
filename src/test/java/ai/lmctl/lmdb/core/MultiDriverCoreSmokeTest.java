package ai.lmctl.lmdb.core;

import java.util.List;
import java.util.Properties;

/** Runs the same bounded core checks against SQLite-JDBC and DuckDB. */
public final class MultiDriverCoreSmokeTest {
    private MultiDriverCoreSmokeTest() {}
    public static void main(String[] args) throws Exception {
        ai.lmctl.lmdb.Drivers.register();
        check("sqlite", "jdbc:sqlite::memory:");
        check("duckdb", "jdbc:duckdb:");
        System.out.println("lmdb SQLite/DuckDB core smoke tests: PASS");
    }
    private static void check(String name, String url) {
        try (Database db = Database.connect(url, new Properties())) {
            if (name.equals("sqlite")) db.query("PRAGMA foreign_keys = ON");
            db.executeScript("CREATE TABLE parent(id INTEGER PRIMARY KEY, label VARCHAR(20)); CREATE TABLE items(id INTEGER PRIMARY KEY, parent_id INTEGER, label VARCHAR(20), CONSTRAINT fk_parent FOREIGN KEY(parent_id) REFERENCES parent(id)); CREATE INDEX items_label_idx ON items(label); CREATE UNIQUE INDEX items_label_unique ON items(parent_id,label); CREATE VIEW items_view AS SELECT id,label FROM items; INSERT INTO parent VALUES (1,'one'); INSERT INTO items VALUES (1,1,'one'),(2,1,'two');");
            Database.QueryResult result = db.query("SELECT id,label FROM items ORDER BY id");
            require(result.rows().size() == 2 && "one".equals(result.rows().getFirst().get(1)), name + " query");
            require(db.tables().rows().stream().anyMatch(r -> "ITEMS".equalsIgnoreCase(String.valueOf(r.get(1)))), name + " tables metadata");
            require(db.views().rows().stream().anyMatch(r -> "ITEMS_VIEW".equalsIgnoreCase(String.valueOf(r.get(1)))), name + " views metadata");
            require(db.columns(null, "items").rows().stream().anyMatch(r -> "LABEL".equalsIgnoreCase(String.valueOf(r.get(2)))), name + " columns metadata");
            require(db.keys(null, "items").rows().stream().anyMatch(r -> "ID".equalsIgnoreCase(String.valueOf(r.get(3)))), name + " keys metadata");
            require(db.foreignKeys(null, "items").rows().stream().anyMatch(r -> "PARENT".equalsIgnoreCase(String.valueOf(r.get(1)))), name + " foreign key metadata");
            var indexes = db.indexes(null, "items");
            require(indexes.rows().stream().anyMatch(r -> "ITEMS_LABEL_IDX".equalsIgnoreCase(String.valueOf(r.get(2)))), name + " indexes metadata");
            if (name.equals("sqlite")) {
                var ordinary = indexes.rows().stream().filter(r -> "ITEMS_LABEL_IDX".equalsIgnoreCase(String.valueOf(r.get(2)))).findFirst().orElseThrow();
                var unique = indexes.rows().stream().filter(r -> "ITEMS_LABEL_UNIQUE".equalsIgnoreCase(String.valueOf(r.get(2)))).findFirst().orElseThrow();
                require(ordinary.get(4) instanceof Number n && n.intValue() != 0, "SQLite nonunique index flag");
                require(unique.get(4) instanceof Number n && n.intValue() == 0, "SQLite unique index flag");
                var snapshotIndexes = db.snapshot().indexes();
                require(snapshotIndexes.stream().anyMatch(i -> i.name().equalsIgnoreCase("ITEMS_LABEL_IDX") && !i.unique()), "SQLite snapshot nonunique flag");
                require(snapshotIndexes.stream().anyMatch(i -> i.name().equalsIgnoreCase("ITEMS_LABEL_UNIQUE") && i.unique()), "SQLite snapshot unique flag");
            }
            Database.SchemaSnapshot first = db.snapshot();
            db.query("ALTER TABLE items ADD COLUMN extra INTEGER");
            require(Database.diff(first, db.snapshot()).rows().stream().anyMatch(r -> String.valueOf(r.get(2)).toLowerCase().endsWith(".extra")), name + " schema diff");
            require(db.explain("SELECT 1").isQuery(), name + " explain");
            require(Database.json(result).contains("\"label\""), name + " JSON");
            if (name.equals("sqlite")) require(((Number) db.query("PRAGMA hard_heap_limit").rows().getFirst().getFirst()).longValue() > 0, "sqlite engine memory cap");
            if (name.equals("duckdb")) require(!db.query("SELECT current_setting('memory_limit')").rows().isEmpty(), "duckdb engine memory cap");
        }
    }
    private static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
}
