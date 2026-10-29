package ai.lmctl.lmclient.areas;

import ai.lmctl.lmclient.core.Env;
import io.lmctl.lmcode.Json;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.StringJoiner;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * github area — port of lmconn's github user/repos ops (read-only, https://api.github.com).
 * PINNED CLI contract (wave 6; owner Fable; details docs/areas/github.md):
 *   lmclient github user
 *   lmclient github repos ORG [--limit N]
 * Token resolution like lmconn: store github api_key > GITHUB_TOKEN/GH_TOKEN env > gh CLI > anonymous.
 * Results carry the token source ("auth" as in lmconn, and "tokenSource"), never the token.
 *   user  -> {login, name, id, publicRepos, auth, tokenSource}
 *   repos -> {org, count, names, repos:[{name, description, stars}], auth, tokenSource}
 * Errors: USAGE (2); MISSING_KEY, AUTH (401/403), NOT_FOUND (404), HTTP (other status), NETWORK,
 * INVALID_RESPONSE (3). LMCLIENT_GITHUB_API overrides the API origin for tests. Envelope per Envelope.java.
 */
public final class GithubArea {
    private GithubArea() {}

    static final String DEFAULT_API = "https://api.github.com";
    private static final String USAGE = "usage: lmclient github user | lmclient github repos ORG [--limit N]";
    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(10);
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(30);
    private static final Pattern NEXT_LINK = Pattern.compile("<([^>]+)>;\\s*rel=\"next\"");

    private record Auth(String token, String source) {}
    private record Reply(int status, Object data, String link) {}

    private static final class Failure extends RuntimeException {
        final String code; final int status;
        Failure(String code, String message) { this(code, message, 0); }
        Failure(String code, String message, int status) { super(message); this.code = code; this.status = status; }
    }
    private static Failure usage(String message) { return new Failure("USAGE", message); }

    public static int run(String[] args) {
        Auth auth = null;
        try {
            if (args.length == 0) throw usage(USAGE);
            String command = args[0];
            if (command.equals("user")) {
                if (args.length > 1) throw usage("usage: lmclient github user");
                auth = resolveToken();
                return Envelope.ok(json(user(auth)));
            }
            if (command.equals("repos")) {
                String org = null; int limit = 30;
                for (int i = 1; i < args.length; i++) {
                    String a = args[i];
                    if (a.equals("--limit")) {
                        if (i + 1 >= args.length) throw usage("missing value for --limit");
                        try { limit = Integer.parseInt(args[++i].trim()); } catch (NumberFormatException e) { throw usage("--limit must be an integer 1..1000"); }
                        if (limit < 1 || limit > 1000) throw usage("--limit must be an integer 1..1000");
                    } else if (a.startsWith("--")) throw usage("unknown option: " + a);
                    else if (org == null) org = a;
                    else throw usage("unexpected argument: " + a);
                }
                if (org == null || org.isBlank()) throw usage("usage: lmclient github repos ORG [--limit N]");
                auth = resolveToken();
                return Envelope.ok(json(repos(org, limit, auth)));
            }
            throw usage(USAGE);
        } catch (Failure e) {
            return Envelope.fail(e.code, scrub(e.getMessage(), auth));
        } catch (RuntimeException e) {
            return Envelope.fail("GITHUB_ERROR", scrub("github command failed: " + e.getClass().getSimpleName(), auth));
        }
    }

    // --- token resolution: store > env > gh > anonymous; the value is never logged ---

    static Auth resolveToken() {
        String stored = null;
        try { stored = CredStore.get("github", "api_key"); } catch (IllegalStateException unavailable) { /* fall through to env */ }
        if (present(stored)) return new Auth(stored, "store");
        for (String name : new String[] {"GITHUB_TOKEN", "GH_TOKEN"}) {
            String value = System.getenv(name);
            if (present(value)) return new Auth(value, "env:" + name);
        }
        String fromGh = ghAuthToken();
        if (present(fromGh)) return new Auth(fromGh, "gh");
        return new Auth(null, "anonymous");
    }

    static String ghAuthToken() {
        try {
            Process process = new ProcessBuilder("gh", "auth", "token")
                .redirectError(ProcessBuilder.Redirect.DISCARD)
                .start();
            process.getOutputStream().close();
            byte[] out = process.getInputStream().readAllBytes();
            if (!process.waitFor(5, TimeUnit.SECONDS)) { process.destroyForcibly(); return null; }
            if (process.exitValue() != 0) return null;
            String token = new String(out, StandardCharsets.UTF_8).trim();
            return token.isEmpty() ? null : token;
        } catch (IOException | InterruptedException | RuntimeException e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            return null;
        }
    }

    // --- operations ---

    static Map<String, Object> user(Auth auth) {
        if (auth.token == null)
            throw new Failure("MISSING_KEY", "github user needs a token: store one with `lmclient cred set github api_key --stdin`, export GITHUB_TOKEN, or log in with gh");
        Map<String, Object> data = Json.object(api("/user", auth).data);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("login", data.get("login"));
        result.put("name", data.getOrDefault("name", null));
        result.put("id", data.get("id"));
        result.put("publicRepos", data.getOrDefault("public_repos", null));
        result.put("auth", auth.source);
        result.put("tokenSource", auth.source);
        return result;
    }

    static Map<String, Object> repos(String org, int limit, Auth auth) {
        List<Object> names = new ArrayList<>();
        List<Object> repos = new ArrayList<>();
        String query = "/repos?per_page=" + Math.min(limit, 100) + "&sort=full_name";
        String path = "/orgs/" + encode(org) + query;
        boolean userFallback = false;
        while (path != null && names.size() < limit) {
            Reply reply;
            try {
                reply = api(path, auth);
            } catch (Failure e) {
                if (e.status == 404 && !userFallback) { // not an organisation: try the user endpoint once
                    userFallback = true;
                    path = "/users/" + encode(org) + query;
                    continue;
                }
                throw e;
            }
            if (!(reply.data instanceof List<?> page)) throw new Failure("INVALID_RESPONSE", "GitHub returned a non-list for repositories");
            for (Object item : page) {
                if (names.size() >= limit) break;
                Map<String, Object> repo = item instanceof Map<?, ?> ? Json.object(item) : Map.of();
                names.add(repo.get("name"));
                Map<String, Object> summary = new LinkedHashMap<>();
                summary.put("name", repo.get("name"));
                summary.put("description", repo.getOrDefault("description", null));
                summary.put("stars", repo.getOrDefault("stargazers_count", null));
                repos.add(summary);
            }
            if (page.isEmpty()) break;
            Matcher next = reply.link == null ? null : NEXT_LINK.matcher(reply.link);
            path = next != null && next.find() ? relative(next.group(1)) : null;
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("org", org);
        result.put("count", names.size());
        result.put("names", names);
        result.put("repos", repos);
        result.put("auth", auth.source);
        result.put("tokenSource", auth.source);
        return result;
    }

    // --- HTTP ---

    static String apiOrigin() {
        String override = Env.get("LMCLIENT_GITHUB_API");
        String origin = present(override) ? override : DEFAULT_API;
        return origin.endsWith("/") ? origin.substring(0, origin.length() - 1) : origin;
    }

    private static String relative(String url) {
        String origin = apiOrigin();
        return url.startsWith(origin) ? url.substring(origin.length()) : url;
    }

    static Reply api(String path, Auth auth) {
        HttpRequest.Builder request = HttpRequest.newBuilder(URI.create(apiOrigin() + path))
            .timeout(REQUEST_TIMEOUT).GET()
            .header("Accept", "application/vnd.github+json")
            .header("User-Agent", "lmclient")
            .header("X-GitHub-Api-Version", "2022-11-28");
        if (auth.token != null) request.header("Authorization", "Bearer " + auth.token);
        HttpResponse<String> response;
        try {
            HttpClient client = HttpClient.newBuilder().connectTimeout(CONNECT_TIMEOUT).followRedirects(HttpClient.Redirect.NORMAL).build();
            response = client.send(request.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            String reason = e instanceof java.net.http.HttpTimeoutException ? "timed out" : (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            throw new Failure("NETWORK", "GitHub request failed: " + reason);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new Failure("NETWORK", "GitHub request interrupted");
        }
        Object data = null;
        if (!response.body().isEmpty()) {
            try { data = Json.parse(response.body()); } catch (IllegalArgumentException ignored) { /* keep null */ }
        }
        int status = response.statusCode();
        if (status < 200 || status >= 300) {
            String detail = data instanceof Map<?, ?> m && m.get("message") instanceof String msg ? ": " + msg : "";
            String hint = status == 401 || status == 403
                ? " (auth: " + auth.source + "; store a token with `lmclient cred set github api_key --stdin`)" : "";
            String code = status == 401 || status == 403 ? "AUTH" : status == 404 ? "NOT_FOUND" : "HTTP";
            throw new Failure(code, "GitHub " + path + " -> HTTP " + status + detail + hint, status);
        }
        return new Reply(status, data, response.headers().firstValue("Link").orElse(null));
    }

    // --- helpers ---

    private static boolean present(String value) { return value != null && !value.isEmpty(); }
    private static String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }

    private static String scrub(String message, Auth auth) {
        if (message == null) return "";
        return auth != null && auth.token != null ? message.replace(auth.token, "[REDACTED]") : message;
    }

    /** JSON for Map/List/String/Number/Boolean values; integral doubles print as integers (GitHub ids, counts). */
    static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof String s) return Envelope.quote(s);
        if (value instanceof Map<?, ?> map) {
            StringJoiner fields = new StringJoiner(",", "{", "}");
            map.forEach((k, v) -> fields.add(Envelope.quote(k.toString()) + ":" + json(v)));
            return fields.toString();
        }
        if (value instanceof List<?> list) {
            StringJoiner items = new StringJoiner(",", "[", "]");
            for (Object item : list) items.add(json(item));
            return items.toString();
        }
        if (value instanceof Double d) {
            if (!Double.isFinite(d)) return "null";
            if (d == Math.rint(d) && Math.abs(d) < 9007199254740992.0) return Long.toString(d.longValue());
            return d.toString();
        }
        return value.toString();
    }
}
