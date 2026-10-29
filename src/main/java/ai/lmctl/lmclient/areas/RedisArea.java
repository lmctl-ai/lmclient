package ai.lmctl.lmclient.areas;

import ai.lmctl.lmclient.Credentials;
import ai.lmctl.lmclient.core.Env;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import javax.net.ssl.SSLParameters;
import redis.clients.jedis.DefaultJedisClientConfig;
import redis.clients.jedis.HostAndPort;
import redis.clients.jedis.Jedis;
import redis.clients.jedis.exceptions.JedisDataException;
import redis.clients.jedis.params.SetParams;

/**
 * Redis: ping, get KEY, set KEY VALUE [--ttl SECONDS], del KEY [KEY...],
 * lpush KEY VALUE [VALUE...], rpop KEY, lrange KEY START STOP, publish CHANNEL MESSAGE.
 * Connection: --url or LMCLIENT_REDIS_URL; secrets from env or --credentials-file.
 * One JSON envelope; exit 0 success, 2 USAGE, 3 CONN/READONLY.
 */
public final class RedisArea {
    private RedisArea() {}
    private static final Set<String> WRITES = Set.of("set", "del", "lpush", "rpop", "publish");
    private static final Set<String> OPTIONS = Set.of("--url", "--timeout", "--ttl", "--credentials-file");
    private static final String USAGE = "Usage: redis ping|get KEY|set KEY VALUE [--ttl SECONDS]|del KEY [KEY...]|lpush KEY VALUE [VALUE...]|rpop KEY|lrange KEY START STOP|publish CHANNEL MESSAGE; --url or LMCLIENT_REDIS_URL required";

    private record Request(String command, List<String> operands, URI uri, int database,
                           int timeout, Long ttl, String credentialsFile, boolean readonly) {}

    public static int run(String[] args) {
        final Request request;
        try { request = parse(args); }
        catch (IllegalArgumentException ex) { return Envelope.fail("USAGE", USAGE); }
        if (request.readonly && WRITES.contains(request.command))
            return Envelope.fail("READONLY", "Redis write command refused by --readonly");
        try {
            var properties = Credentials.read(request.credentialsFile);
            String user = null;
            String password = null;
            String info = request.uri.getRawUserInfo();
            if (info != null) {
                String[] parts = info.split(":", 2);
                user = decode(parts[0]);
                password = parts.length == 2 ? decode(parts[1]) : null;
                if (user.isEmpty()) user = null;
            }
            user = properties.getProperty("user", user);
            password = properties.getProperty("password", password);
            if (Env.get("LMCLIENT_REDIS_USER") != null) user = Env.get("LMCLIENT_REDIS_USER");
            if (Env.get("LMCLIENT_REDIS_PASSWORD") != null) password = Env.get("LMCLIENT_REDIS_PASSWORD");
            var config = DefaultJedisClientConfig.builder()
                    .connectionTimeoutMillis(request.timeout).socketTimeoutMillis(request.timeout)
                    .blockingSocketTimeoutMillis(request.timeout).database(request.database);
            if (user != null && !user.isEmpty()) config.user(user);
            if (password != null) config.password(password);
            if (request.uri.getScheme().equals("rediss")) {
                var ssl = new SSLParameters();
                ssl.setEndpointIdentificationAlgorithm("HTTPS");
                config.ssl(true).sslParameters(ssl);
            }
            String result;
            try (var redis = new Jedis(new HostAndPort(request.uri.getHost(),
                    request.uri.getPort() == -1 ? 6379 : request.uri.getPort()), config.build())) {
                var p = request.operands;
                result = switch (request.command) {
                    case "ping" -> "{\"pong\":" + Envelope.quote(redis.ping()) + "}";
                    case "get" -> value(redis.get(p.get(0)));
                    case "set" -> {
                        var params = new SetParams();
                        if (request.ttl != null) params.ex(request.ttl);
                        String reply = redis.set(p.get(0), p.get(1), params);
                        if (!"OK".equals(reply)) throw new IllegalStateException();
                        yield "{\"stored\":true}";
                    }
                    case "del" -> "{\"deleted\":" + redis.del(p.toArray(String[]::new)) + "}";
                    case "lpush" -> "{\"length\":" + redis.lpush(p.get(0), p.subList(1, p.size()).toArray(String[]::new)) + "}";
                    case "rpop" -> value(redis.rpop(p.get(0)));
                    case "lrange" -> "{\"values\":" + redis.lrange(p.get(0), Long.parseLong(p.get(1)), Long.parseLong(p.get(2)))
                            .stream().map(Envelope::quote).collect(Collectors.joining(",", "[", "]")) + "}";
                    case "publish" -> "{\"receivers\":" + redis.publish(p.get(0), p.get(1)) + "}";
                    default -> throw new IllegalStateException();
                };
            }
            return Envelope.ok(result);
        } catch (JedisDataException ex) {
            if (ex.getMessage() != null && ex.getMessage().startsWith("READONLY "))
                return Envelope.fail("READONLY", "Redis server refused a write on a read-only replica");
            return Envelope.fail("CONN", "Redis authentication or command failed");
        } catch (Exception ex) {
            // URLs, authentication errors, paths, and server responses can contain secrets.
            return Envelope.fail("CONN", "Redis connection, credentials, or command failed");
        }
    }

    private static String value(String value) { return "{\"value\":" + Envelope.quote(value) + "}"; }
    private static String decode(String value) {
        return URLDecoder.decode(value.replace("+", "%2B"), StandardCharsets.UTF_8);
    }

    private static Request parse(String[] args) {
        var options = new HashMap<String, String>();
        var words = new ArrayList<String>();
        boolean literal = false;
        boolean readonly = false;
        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            if (!literal && arg.equals("--")) { literal = true; continue; }
            if (!literal && arg.equals("--readonly")) { readonly = true; continue; }
            if (!literal && arg.startsWith("--")) {
                if (!OPTIONS.contains(arg) || options.containsKey(arg) || i + 1 >= args.length || args[i + 1].startsWith("--"))
                    throw new IllegalArgumentException();
                options.put(arg, args[++i]);
            } else words.add(arg);
        }
        if (words.isEmpty()) throw new IllegalArgumentException();
        String command = words.remove(0);
        boolean valid = switch (command) {
            case "ping" -> words.isEmpty();
            case "get", "rpop" -> words.size() == 1;
            case "set", "publish" -> words.size() == 2;
            case "lrange" -> words.size() == 3;
            case "del" -> !words.isEmpty();
            case "lpush" -> words.size() >= 2;
            default -> false;
        };
        if (!valid || (options.containsKey("--ttl") && !command.equals("set"))) throw new IllegalArgumentException();
        if (command.equals("lrange")) { Long.parseLong(words.get(1)); Long.parseLong(words.get(2)); }
        Long ttl = options.containsKey("--ttl") ? Long.valueOf(options.get("--ttl")) : null;
        int timeout = Integer.parseInt(options.getOrDefault("--timeout", "10000"));
        if (timeout <= 0 || (ttl != null && ttl <= 0)) throw new IllegalArgumentException();
        String url = options.getOrDefault("--url", Env.get("LMCLIENT_REDIS_URL"));
        if (url == null) throw new IllegalArgumentException();
        URI uri = URI.create(url);
        if (!Set.of("redis", "rediss").contains(uri.getScheme() == null ? "" : uri.getScheme()) ||
                uri.getHost() == null || uri.getRawQuery() != null || uri.getRawFragment() != null ||
                uri.getPort() == 0 || uri.getPort() > 65535) throw new IllegalArgumentException();
        String path = uri.getPath();
        if (path == null || !path.matches("/?[0-9]*")) throw new IllegalArgumentException();
        int database = path.isEmpty() || path.equals("/") ? 0 : Integer.parseInt(path.substring(1));
        return new Request(command, words, uri, database, timeout, ttl,
                options.getOrDefault("--credentials-file", Env.get("LMCLIENT_CREDENTIALS_FILE")), readonly);
    }
}
