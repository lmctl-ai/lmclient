package ai.lmctl.lmclient.areas;

import ai.lmctl.lmclient.Credentials;
import ai.lmctl.lmclient.core.Env;
import com.mongodb.ConnectionString;
import com.mongodb.MongoClientSettings;
import com.mongodb.MongoCommandException;
import com.mongodb.MongoCredential;
import com.mongodb.MongoException;
import com.mongodb.MongoSecurityException;
import com.mongodb.MongoSocketException;
import com.mongodb.MongoTimeoutException;
import com.mongodb.MongoWriteException;
import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoCollection;
import org.bson.Document;
import org.bson.json.JsonMode;
import org.bson.json.JsonParseException;
import org.bson.json.JsonWriterSettings;
import org.bson.types.ObjectId;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * mongo area — replaces n8n's MongoDB node.
 * PINNED CLI contract (wave 5b; owner Fable; details docs/areas/mongo.md):
 *   lmclient mongo ping --url mongodb://host:27017
 *   lmclient mongo insert --url ... --db D --collection C --doc '{"json"}' | --doc-file PATH
 *   lmclient mongo find --url ... --db D --collection C [--filter '{"json"}' | --filter-file PATH] [--limit N]
 *   lmclient mongo delete --url ... --db D --collection C --filter '{"json"}' | --filter-file PATH
 * --doc-file / --filter-file read the JSON document from a UTF-8 file (like http --data-file): the portable
 * way to pass documents whose quotes a platform's argv handling would mangle (Windows JVM launcher).
 * Common flags: --timeout MS (default 10000), --credentials-file FILE (java .properties with
 * user/password; LMCLIENT_USER / LMCLIENT_PASSWORD also work). LMCLIENT_MONGO_URL env fallback.
 * Envelope per Envelope.java; error codes CONN (cannot reach or authenticate), USAGE, BAD_JSON
 * (both exit 2), SERVER (the server rejected a command, e.g. a write error or an invalid operator).
 * Client: mongodb-driver-sync (never the reactive driver — Netty). Secrets never reach stdout/stderr.
 */
public final class MongoArea {
    private MongoArea() {}

    private static final Set<String> COMMANDS = Set.of("ping", "insert", "find", "delete");
    private static final Set<String> OPTIONS = Set.of("--url", "--db", "--collection", "--doc", "--doc-file", "--filter", "--filter-file", "--limit", "--timeout", "--credentials-file");
    private static final int DEFAULT_LIMIT = 100;
    private static final int MAX_LIMIT = 10000;
    private static final String USAGE =
        "usage: lmclient mongo ping|insert|find|delete --url mongodb://host:27017 [--db D --collection C] " +
        "[--doc JSON | --doc-file PATH] [--filter JSON | --filter-file PATH] [--limit N] [--timeout MS] [--credentials-file FILE]";
    private static final JsonWriterSettings JSON = JsonWriterSettings.builder().outputMode(JsonMode.RELAXED).build();

    public static int run(String[] args) {
        Logger.getLogger("org.mongodb.driver").setLevel(Level.SEVERE);
        String secret = null;
        try {
            if (args.length == 0 || !COMMANDS.contains(args[0])) throw usage(USAGE);
            String command = args[0];
            Map<String, String> options = new LinkedHashMap<>();
            for (int i = 1; i < args.length; i++) {
                if (!OPTIONS.contains(args[i])) throw usage("unknown option " + args[i] + "; " + USAGE);
                if (i + 1 == args.length) throw usage("option " + args[i] + " requires a value");
                if (options.put(args[i], args[++i]) != null) throw usage("duplicate option " + args[i]);
            }
            String url = options.getOrDefault("--url", Env.get("LMCLIENT_MONGO_URL"));
            if (url == null || url.isBlank()) throw usage("a MongoDB URL is required (--url or LMCLIENT_MONGO_URL)");
            if (!url.startsWith("mongodb://") && !url.startsWith("mongodb+srv://")) throw usage("the URL must start with mongodb:// or mongodb+srv://");
            int timeoutMs = positive(options.getOrDefault("--timeout", "10000"), "--timeout", Integer.MAX_VALUE);
            Properties credentials = Credentials.read(options.get("--credentials-file"));
            secret = credentials.getProperty("password");

            if (command.equals("ping")) {
                forbid(options, "--db", "--collection", "--doc", "--doc-file", "--filter", "--filter-file", "--limit");
                try (MongoClient client = connect(url, credentials, timeoutMs)) {
                    Document reply = client.getDatabase("admin").runCommand(new Document("ping", 1));
                    return Envelope.ok("{\"pong\":" + (reply.get("ok") instanceof Number n && n.doubleValue() == 1.0) + "}");
                }
            }
            String db = required(options, "--db");
            String collection = required(options, "--collection");
            switch (command) {
                case "insert" -> {
                    forbid(options, "--filter", "--filter-file", "--limit");
                    Document doc = parse(jsonOption(options, "--doc", true), "--doc");
                    try (MongoClient client = connect(url, credentials, timeoutMs)) {
                        var result = collection(client, db, collection).insertOne(doc);
                        String id = result.getInsertedId() == null ? stringId(doc.get("_id")) : stringId(result.getInsertedId());
                        return Envelope.ok("{\"insertedId\":" + Envelope.quote(id) + "}");
                    }
                }
                case "find" -> {
                    forbid(options, "--doc", "--doc-file");
                    String filterJson = jsonOption(options, "--filter", false);
                    Document filter = filterJson == null ? new Document() : parse(filterJson, "--filter");
                    int limit = positive(options.getOrDefault("--limit", Integer.toString(DEFAULT_LIMIT)), "--limit", MAX_LIMIT);
                    try (MongoClient client = connect(url, credentials, timeoutMs)) {
                        List<String> docs = new ArrayList<>();
                        for (Document d : collection(client, db, collection).find(filter).limit(limit).maxTime(timeoutMs, TimeUnit.MILLISECONDS)) {
                            if (d.containsKey("_id")) d.put("_id", stringId(d.get("_id")));
                            docs.add(d.toJson(JSON));
                        }
                        return Envelope.ok("{\"count\":" + docs.size() + ",\"docs\":[" + String.join(",", docs) + "]}");
                    }
                }
                case "delete" -> {
                    forbid(options, "--doc", "--doc-file", "--limit");
                    Document filter = parse(jsonOption(options, "--filter", true), "--filter");
                    try (MongoClient client = connect(url, credentials, timeoutMs)) {
                        long deleted = collection(client, db, collection).deleteMany(filter).getDeletedCount();
                        return Envelope.ok("{\"deleted\":" + deleted + "}");
                    }
                }
                default -> throw usage(USAGE);
            }
        } catch (Usage e) {
            return Envelope.fail("USAGE", e.getMessage());
        } catch (BadJson e) {
            Envelope.fail("BAD_JSON", e.getMessage());
            return 2; // malformed input is a usage-class error
        } catch (MongoTimeoutException | MongoSocketException | MongoSecurityException e) {
            return Envelope.fail("CONN", scrub("cannot reach or authenticate with MongoDB: " + connectionMessage(e), secret));
        } catch (MongoCommandException e) {
            return Envelope.fail("SERVER", scrub("MongoDB rejected the operation (" + e.getErrorCodeName() + "): " + e.getErrorMessage(), secret));
        } catch (MongoWriteException e) {
            return Envelope.fail("SERVER", scrub("MongoDB rejected the write (" + e.getError().getCategory() + "): " + e.getError().getMessage(), secret));
        } catch (MongoException e) {
            return Envelope.fail("CONN", scrub("MongoDB error: " + rootMessage(e), secret));
        } catch (IllegalArgumentException e) {
            return Envelope.fail("USAGE", scrub(e.getMessage(), secret));
        } catch (java.io.IOException e) {
            return Envelope.fail("USAGE", "cannot read --credentials-file: " + e.getClass().getSimpleName());
        } catch (RuntimeException e) {
            return Envelope.fail("CONN", scrub("mongo command failed: " + e.getClass().getSimpleName() + ": " + rootMessage(e), secret));
        }
    }

    private static MongoClient connect(String url, Properties credentials, int timeoutMs) {
        ConnectionString connection = new ConnectionString(url);
        var settings = MongoClientSettings.builder().applyConnectionString(connection)
            .applyToClusterSettings(b -> b.serverSelectionTimeout(timeoutMs, TimeUnit.MILLISECONDS))
            .applyToSocketSettings(b -> b.connectTimeout(timeoutMs, TimeUnit.MILLISECONDS).readTimeout(timeoutMs, TimeUnit.MILLISECONDS))
            .applicationName("lmclient");
        String user = credentials.getProperty("user");
        String password = credentials.getProperty("password");
        if (user != null && password != null) {
            String source = connection.getDatabase() != null ? connection.getDatabase() : "admin";
            settings.credential(MongoCredential.createCredential(user, source, password.toCharArray()));
        }
        return MongoClients.create(settings.build());
    }

    private static MongoCollection<Document> collection(MongoClient client, String db, String collection) {
        return client.getDatabase(db).getCollection(collection);
    }

    /** Inline JSON from --flag or the UTF-8 contents of --flag-file; exactly one of them when required. */
    private static String jsonOption(Map<String, String> options, String flag, boolean mandatory) {
        String inline = options.get(flag);
        String file = options.get(flag + "-file");
        if (inline != null && file != null) throw usage("use only one of " + flag + " and " + flag + "-file");
        if (file != null) {
            try {
                return java.nio.file.Files.readString(java.nio.file.Path.of(file), java.nio.charset.StandardCharsets.UTF_8);
            } catch (java.io.IOException | java.nio.file.InvalidPathException e) {
                throw usage("cannot read " + flag + "-file: " + e.getClass().getSimpleName());
            }
        }
        if (inline == null || inline.isBlank()) {
            if (!mandatory) return null;
            throw usage(flag + " or " + flag + "-file is required; " + USAGE);
        }
        return inline;
    }

    private static Document parse(String json, String flag) {
        try {
            return Document.parse(json);
        } catch (JsonParseException | org.bson.BsonInvalidOperationException | IllegalArgumentException e) {
            throw new BadJson(flag + " is not a JSON object: " + e.getMessage());
        }
    }

    private static String stringId(Object id) {
        if (id instanceof ObjectId oid) return oid.toHexString();
        if (id instanceof org.bson.BsonObjectId oid) return oid.getValue().toHexString();
        if (id instanceof org.bson.BsonValue v) return v.isString() ? v.asString().getValue() : v.toString();
        return String.valueOf(id);
    }

    private static String required(Map<String, String> options, String flag) {
        String value = options.get(flag);
        if (value == null || value.isBlank()) throw usage(flag + " is required; " + USAGE);
        return value;
    }

    private static void forbid(Map<String, String> options, String... flags) {
        for (String flag : flags) if (options.containsKey(flag)) throw usage(flag + " does not apply to this command");
    }

    private static int positive(String raw, String flag, int max) {
        try {
            int value = Integer.parseInt(raw.trim());
            if (value < 1 || value > max) throw usage(flag + " must be between 1 and " + max);
            return value;
        } catch (NumberFormatException e) {
            throw usage(flag + " must be a positive whole number");
        }
    }

    /** Driver timeouts wrap the real cause in a long cluster description; keep the last cause and the host. */
    private static String connectionMessage(Throwable e) {
        String message = e.getMessage() == null ? "" : e.getMessage();
        var cause = java.util.regex.Pattern.compile("caused by \\{([^}]*)\\}").matcher(message);
        String last = null;
        while (cause.find()) last = cause.group(1);
        var address = java.util.regex.Pattern.compile("address=([^,}\\s]+)").matcher(message);
        String host = address.find() ? address.group(1) : null;
        if (last == null) return rootMessage(e);
        last = last.replaceFirst("^[A-Za-z0-9_.$]+Exception: ", "");
        return (host == null ? "" : host + ": ") + last + (e instanceof MongoTimeoutException ? " (timed out waiting for a server)" : "");
    }

    private static String rootMessage(Throwable e) {
        Throwable t = e;
        while (t.getCause() != null && t.getCause() != t) t = t.getCause();
        String message = t.getMessage() == null ? t.getClass().getSimpleName() : t.getMessage();
        return message.replaceAll("\\s+", " ").trim();
    }

    /** Redacts the password value and any user:password@ part of a connection string. */
    private static String scrub(String message, String secret) {
        if (message == null) return "";
        String out = secret == null || secret.isEmpty() ? message : message.replace(secret, "[REDACTED]");
        return out.replaceAll("(mongodb(?:\\+srv)?://)[^@\\s]+@", "$1[REDACTED]@");
    }

    private static Usage usage(String message) { return new Usage(message); }

    private static final class Usage extends RuntimeException { Usage(String m) { super(m); } }
    private static final class BadJson extends RuntimeException { BadJson(String m) { super(m); } }
}
