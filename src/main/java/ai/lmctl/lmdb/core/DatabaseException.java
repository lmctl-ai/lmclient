package ai.lmctl.lmdb.core;

import java.sql.SQLException;

/** Runtime error whose message is safe for command line display. */
public final class DatabaseException extends RuntimeException {
    public DatabaseException(String message) { super(message); }
    public DatabaseException(String message, Throwable cause) { super(message, cause); }
    static DatabaseException from(SQLException error) {
        String state = error.getSQLState();
        String suffix = state == null || !state.matches("[A-Za-z0-9]{5}") ? "" : " (SQLState " + state + ")";
        return new DatabaseException("database operation failed" + suffix, error);
    }
    static DatabaseException from(RuntimeException error) {
        return new DatabaseException("database operation failed", error);
    }
}
