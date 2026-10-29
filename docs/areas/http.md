# HTTP Request

`lmclient http request URL [--method M] [--header 'Name: value' ...] [--data STRING | --data-file PATH] [--auth SERVICE] [--timeout MS]`

Default method is GET, or POST when data is supplied. GET/HEAD omit request bodies. JSON data automatically receives `application/json`; other data receives `text/plain; charset=utf-8`. Explicit headers win; repeated header values are joined with commas. Timeout defaults to 30000 ms and covers the complete response, including a stalled body. HTTP statuses, including 4xx/5xx, are successful command envelopes with `result.ok=false` for statuses >=400. There are no retries or redirects.

The result contains `status`, `ok`, `contentType`, `latencyMs`, `url`, and `bodyJson` when parsing succeeds, otherwise `bodyText`. For authenticated requests, `keySource` is `store`, `env:NAME`, or `store-oauth`; unauthenticated requests omit it. Response bodies and request body files are limited to 10 MiB. An oversized response returns `BODY_TOO_LARGE`, exit 3.

Authentication uses the family `CredStore`: stored `api_key`, then uppercase service name with non-alphanumeric characters replaced by `_` plus `_API_KEY`, then stored `oauth_access_token`. Expired OAuth tokens refresh through the stored token URL with HTTP Basic or form-body client authentication. Missing replacement refresh tokens preserve the previous value; missing expiry clears stale expiry. Expired credentials without refresh tokens and `invalid_grant` return `RECONNECT`. Other refresh failures return sanitized `OAUTH_REFRESH`. The public `HttpArea.refreshOAuth(service, timeoutMs)` helper uses the `oauth_*` storage contract without depending on the OAuth command implementation.

Selected API/OAuth secrets are redacted recursively from response strings and JSON keys. Explicit authorization and cookie header values are also redacted. Error messages never include server diagnostics, credential values, or arbitrary request arguments. Embedded URL userinfo is rejected; use `--auth` or an authorization header instead.

## Known limitations

On Windows, quote-heavy JSON passed through `--data` can lose embedded quotes during argv transport and be treated as plain text. Use `--data-file PATH` with a UTF-8 JSON file to preserve the payload and automatic `application/json` detection.

## wiring

- No new Maven dependencies or POM changes. Uses JDK `java.net.http.HttpClient`, existing `CredStore`, and the already bundled lmcode SDK's reflection-free JSON parser.
- Build: `mvn -q -B package -DskipTests`.
- Test: `python3 scripts/test-http.py target/lmclient-0.2.0-all.jar` (also accepts a native executable).
- Tests start a loopback Python `ThreadingHTTPServer` for both token and API endpoints; temporary credential DBs are seeded with Python's standard `sqlite3` module. No Docker, network services, or working cred command required. Server and DB connections are closed before cleanup.
- Shared temporary-directory cleanup retries `PermissionError` ten times at 500 ms intervals after connections and child processes close; persistent locks still fail. Cleanup regression checks: `python3 scripts/test-temp-cleanup.py`.
- No extra reflection metadata. Native-image testing is deferred to CI; local verification is JVM-only.

## Reference differences

The local lmconn reference read for this port uses `redirect: 'follow'`, has no response-cap constant, and does not emit `keySource`. This port follows the explicitly pinned Java brief instead: redirects NEVER, a documented 10 MiB limit, and source-only credential metadata. Runtime errors use the family Java exit code 3 rather than lmconn's 1. Timeouts are bounded to positive Java integers (milliseconds).

The existing SDK JSON parser rejects duplicate object keys and nesting beyond 128; such responses are returned as `bodyText` (and such request data gets text content type). It uses Java doubles, like JavaScript numbers. Nonfinite parsed numbers serialize as JSON null rather than invalid JSON. Java's restricted headers (for example Host and Content-Length) and unsupported methods produce sanitized USAGE errors. Automatic compressed-body decoding is not added; no Accept-Encoding header is sent by default.
