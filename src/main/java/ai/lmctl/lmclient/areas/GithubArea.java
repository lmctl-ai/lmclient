package ai.lmctl.lmclient.areas;

/**
 * github area — port of lmconn's github user/repos ops.
 * PINNED CLI contract (wave 6; owner Fable; details docs/areas/github.md):
 *   lmclient github user
 *   lmclient github repos ORG [--limit N]
 * Token resolution like lmconn: store github api_key > GITHUB_TOKEN/GH_TOKEN env > gh CLI > anonymous.
 * Build on HttpArea's request helper if Fable's wiring allows; otherwise java.net.http directly.
 * Envelope per Envelope.java; never print the token.
 */
public final class GithubArea {
    private GithubArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "github area not implemented yet"); }
}
