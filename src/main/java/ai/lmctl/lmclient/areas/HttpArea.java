package ai.lmctl.lmclient.areas;

/**
 * http area — port of lmconn's http_request (replaces n8n's HTTP Request node).
 * PINNED CLI contract (wave 6; owner Astra2; details docs/areas/http.md):
 *   lmclient http request URL [--method M] [--header 'N: V' ...] [--data STR | --data-file PATH]
 *                             [--auth SERVICE] [--timeout MS]
 * --auth resolution (same as lmconn): store api_key > <SERVICE>_API_KEY env > oauth token
 * (auto-refresh when expired, RECONNECT on invalid_grant) — via CredStore + OauthArea helpers.
 * Result: {"status","ok","contentType","latencyMs","url","bodyJson"?,"bodyText"?} — lmconn-compatible.
 * Client: java.net.http.HttpClient. Envelope per Envelope.java.
 */
public final class HttpArea {
    private HttpArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "http area not implemented yet"); }
}
