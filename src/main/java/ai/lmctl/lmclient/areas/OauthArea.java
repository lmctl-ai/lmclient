package ai.lmctl.lmclient.areas;

/**
 * oauth area — port of lmconn's oauth authorize/refresh/status (PKCE + loopback callback).
 * PINNED CLI contract (wave 6; owner Astra3; details docs/areas/oauth.md):
 *   lmclient oauth authorize SERVICE [--client-id --client-secret --auth-url --token-url
 *       --scope --auth-query --auth-style header|body --port N --timeout MS --no-pkce --manual --auto-follow]
 *   lmclient oauth refresh SERVICE
 *   lmclient oauth status SERVICE
 * Storage: oauth_* fields via CredStore (same contract as lmconn). Vendor presets: embed a copy of
 * lmconn's src/oauth-presets.json as a resource (say so in docs/areas/oauth.md wiring).
 * Tests must run against the SHARED mock IdP: spawn `node ~/lmworkflow/lmconn/scripts/mock-idp.js`
 * (cross-language oracle — n8n passed it). Envelope per Envelope.java.
 */
public final class OauthArea {
    private OauthArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "oauth area not implemented yet"); }
}
