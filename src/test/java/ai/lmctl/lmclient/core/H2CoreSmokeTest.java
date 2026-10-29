package ai.lmctl.lmclient.core;

import java.util.Arrays;
import java.util.List;
import java.util.Properties;

/** Real-driver regression test; invoked by scripts/test-core.sh when H2 is available. */
public final class H2CoreSmokeTest {
    private H2CoreSmokeTest() {}
    public static void main(String[] args) {
        Properties properties = new Properties(); properties.setProperty("lmclient.maxRows", "2"); properties.setProperty("lmclient.maxCellBytes", "32");
        try (Database db = Database.connect("jdbc:h2:mem:lmclient_core;DB_CLOSE_DELAY=-1", properties)) {
            db.executeScript("CREATE TABLE parent(id INT PRIMARY KEY, name VARCHAR(20)); CREATE TABLE child(id INT PRIMARY KEY, parent_id INT, CONSTRAINT fk_parent FOREIGN KEY(parent_id) REFERENCES parent(id)); INSERT INTO parent VALUES(1,'one'),(2,'two');");
            check(db.query("SELECT id,name FROM parent ORDER BY id").rows().size() == 2, "H2 query");
            check("bound".equals(db.query("SELECT ?", List.of("bound"), 2).rows().getFirst().getFirst()), "prepared parameter");
            check(db.foreignKeys("PUBLIC", "CHILD").rows().size() == 1, "foreign key metadata");
            boolean overflow = false;
            try { db.query("SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3"); } catch (DatabaseException expected) { overflow = true; }
            check(overflow, "row limit must not truncate silently");
            boolean cellLimit = false;
            try { db.query("SELECT REPEAT('x', 100)"); } catch (DatabaseException expected) { cellLimit = true; }
            check(cellLimit, "cell limit");
        }
        try (Database db = Database.connect("jdbc:h2:mem:lmclient_core;DB_CLOSE_DELAY=-1", new Properties())) {
            Database.SchemaSnapshot first = db.snapshot();
            db.query("ALTER TABLE parent ADD COLUMN extra VARCHAR(4)");
            Database.SchemaSnapshot second = db.snapshot();
            var changes = Database.diff(first, second);
            check(changes.rows().stream().anyMatch(row -> String.valueOf(row.get(2)).toLowerCase().endsWith(".extra")), "schema diff");
        }
        System.out.println("lmclient H2 core smoke tests: PASS");
    }
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
