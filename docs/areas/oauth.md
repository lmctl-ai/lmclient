# OAuth2

`lmclient oauth authorize SERVICE` implements the lmconn authorization-code
flow with PKCE S256 and a random state. `oauth refresh SERVICE` renews the
stored token; `oauth status SERVICE` returns metadata without tokens.

Authorize options: `--client-id`, `--client-secret`, `--auth-url`, `--token-url`,
`--scope`, `--auth-query`, `--auth-style header|body`, `--port` (default 0),
`--timeout` (milliseconds, default 300000), `--no-pkce`, `--manual`, and
`--auto-follow`. Manual and auto-follow are mutually exclusive. `--json` is
accepted for compatibility; stdout always contains one JSON envelope.
Prefer storing client secrets with `cred set SERVICE oauth_client_secret --stdin`
or `--env` instead of passing them in argv.

Configuration resolution is flags, then `CredStore` fields prefixed `oauth_`,
then the bundled vendor presets. Presets supply endpoints and scopes, never
client credentials. Provider templates such as tenant/subdomain expressions
are not expanded: supply concrete URLs as flags or stored fields.

The callback listener binds only `127.0.0.1`, at `/callback`. The authorization
URL goes to stderr. Open it in a browser, or use `--manual` and paste the full
redirect URL on stdin. `--auto-follow` follows the URL itself for local demos
and mock IdPs; it cannot complete interactive provider consent. The command
validates state and redirect origin/path before exchanging a code. Reserved
parameters override extra provider query parameters; sensitive token/code
parameters are removed from the printed URL. Token exchange never follows
redirects. Responses may be JSON or form encoded.

Status result: `{service, authorized, expiresAt, expired, hasRefreshToken,
scope, tokenUrl}`. Authorize/refresh results: `{service, expiresAt,
hasRefreshToken, scope}`. Expiry is an ISO instant computed from `expires_in`;
missing expiry becomes null. Numeric strings are accepted, like lmconn.
Refresh retains the previous refresh token if the response omits one;
re-authorization without a refresh token removes the old one. A rejected
grant is `RECONNECT`, meaning authorize again.

Failures use `USAGE` (exit 2), or `MISSING_CONFIG`, `OAUTH_ERROR`, `TIMEOUT`,
and `RECONNECT` (exit 3). Underlying exception text and token-endpoint error
bodies are never printed. Refresh has a 30-second network deadline.

## Java integration

`OauthArea.refresh(service)` is a silent public helper for the HTTP area's
auto-refresh path. It stores new tokens and returns metadata JSON, never the
access token. `OauthArea.status(service)` returns the status JSON without
printing it. `OauthArea.OAuthException` exposes a sanitized `code` field and
message. Callers obtain the token from `CredStore` after refreshing.

## wiring

- Additional lmmock tier runs in the same script on JVM and all five native CI
  platforms, using loopback sockets without Docker. `scripts/lmmock-helpers.py`
  resolves `LMMOCK_BIN`, then PATH, then downloads release **0.1.4** (override
  `LMMOCK_VERSION`) to `build/lmmock-cache/`, verifying `SHA256SUMS`.
  An unavailable executable/download prints `SKIP` and exits 0; an explicit
  `LMMOCK_BIN=/nonexistent` forces that path. Checksum, compilation, readiness,
  and assertion failures fail the suite. CI sets `LMMOCK_REQUIRED=1`, so missing
  dependencies fail there too. Children use bounded readiness and termination.
  CI installs an isolated mock compiler `@lmctl-ai/lmctl@0.2.444` via
  `LMMOCK_LMSCRIPT_JS`, retaining the existing example compiler. The harness
  invokes this JS entry with Node directly, compiles to temporary bytecode, then
  runs `lmmock serve --lmcode` on every platform. It stages the source beside
  `schema.json` exported from the exact serving binary, preserving raw bytes
  without newline conversion; no checked-in or release-archive schema is used.
  Local runs default to
  `LMSCRIPT_BIN` or `lmscript` on PATH. Compiler and server startup errors include
  stderr (last 16 KiB); compilation failures never become skips.
- The IdP comes from the checksum-verified `examples.tar.gz` of that same
  release (script only). No OAuth handler copy is vendored: lmmock is
  the single source of truth, pinned for reproducibility. Tests mirror lmconn's
  PKCE S256, header/body client authentication, JSON/form tokens, protected
  userinfo, rotating refresh tokens, revoked grants, bad state, malformed JSON,
  server errors, string/missing expiry, and unknown token fields. The existing
  Node oracle remains for additional manual and adversarial cases.

- No new Maven dependencies or POM changes. JDK networking, cryptography,
  and the existing `CredStore`/SQLite implementation are used.
- Test: `python3 scripts/test-oauth.py target/lmclient-0.2.0-all.jar`;
  the same script also accepts a native executable path.
- Oracle: Node plus the strict mock IdP vendored in this repository at
  `scripts/mock-idp.js` (RFC 6749 + PKCE; canonical copy in lmconn, synced on
  change). `LMCONN_MOCK_IDP` overrides the path. CI runners have Node, so CI
  runs the full cross-language suite; only a machine without `node` on PATH
  runs the usage and status tests alone and prints SKIPPED for the rest.
- The Python harness starts Node importing the shared mock's factory.
  Its standalone entry point lacks fault-mode flags and a request-log API,
  so the child wrapper supplies those controls and emits the mock's redacted
  log on stdout. It does not implement another OAuth server. It verifies
  one authorize and one token request per successful flow; bad state must
  produce zero token requests. Protected userinfo is checked with Python's
  standard-library HTTP client using the Java-issued token, independently
  of the separate HTTP-area port.
- `src/main/resources/oauth-presets.json` is copied verbatim from lmconn's
  `src/oauth-presets.json`. Update it by copying the reviewed source file;
  no runtime dependency on the lmconn checkout. A small bounded JSON reader
  in `OauthArea` handles presets, token fields, and unknown nested fields.
- Native resource inclusion:
  `META-INF/native-image/ai.lmctl/lmclient-oauth/resource-config.json`.
  The callback uses `ServerSocket`, not `com.sun.net.httpserver`, and no
  reflective server setup. Native networking/TLS/resource loading still
  needs CI verification; no native build is attempted locally.

## Deliberate limits and differences

The supplied `CredStore` API commits each field independently and exposes no
multi-field transaction. Saving validates the entire response first, snapshots
old fields, writes the access token last, and attempts rollback on failure.
This is **not an atomic SQLite transaction**, unlike lmconn. A crash or another
process can observe partial changes; cross-process refresh locking is also
not provided. All storage access stays through the shared `CredStore` API.

Response bodies are capped at 1 MiB and JSON nesting at 32; callback request
lines/headers are bounded. These limits protect a small CLI from unbounded
provider responses. Unknown response fields are tolerated and discarded.
Secrets in the generated authorization URL follow lmconn's reserved-parameter
filter; do not put arbitrary secrets in extra query parameters.

Real-provider browser consent, native-image behavior, and the separate HTTP
area's auto-refresh integration require their own verification. No client
registration, client-credentials grant, device flow, or OAuth 1.0a is added.

## verification

`mvn -q -B package -DskipTests` passed on JDK 21 in the isolated OAuth
worktree. `python3 scripts/test-oauth.py target/lmclient-0.2.0-all.jar`
passed 35 checks against the shared Node mock. The mock verified S256 and
state, header/body client authentication, JSON/form token responses, token
rotation and retention, malformed responses, denied grants, and timeouts.
Java-issued tokens successfully accessed the mock's protected userinfo API.
The bundled presets match lmconn's source JSON byte for byte.
