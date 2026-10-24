package ai.lmctl.lmdb.core;

import java.sql.SQLException;

/** Runtime error whose message is safe for command line display. */
public final class DatabaseException extends RuntimeException {
    public DatabaseException(String message) { super(message); }
    public DatabaseException(String message, Throwable cause) { super(message, cause); }
    static DatabaseException from(SQLException error) {
        String message = error.getMessage();
        if (message == null || message.isBlank()) message = "database operation failed";
        // Driver messages can include JDBC URLs and passwords. Keep only the first line and redact common secrets.
        message = message.split("[\\r\\n]", 2)[0]
                .replaceAll("(?i)(password|passwd|pwd|secret|token)=([^ ;,]*)", "$1=[redacted]");
        return new DatabaseException(message, error);
    }
}
