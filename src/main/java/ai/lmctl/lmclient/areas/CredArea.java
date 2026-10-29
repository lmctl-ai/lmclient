package ai.lmctl.lmclient.areas;

/**
 * cred area — the family credential store (shared SQLite schema with lmconn).
 * PINNED CLI contract (wave 6; owner Astra1; details docs/areas/cred.md):
 *   lmclient cred set SERVICE FIELD (--value V | --env VAR | --stdin)
 *   lmclient cred get SERVICE FIELD [--reveal]
 *   lmclient cred list
 *   lmclient cred delete SERVICE FIELD
 *   lmclient cred path
 * Storage: CredStore.java (already implemented). Envelope per Envelope.java.
 * Never print values except `get --reveal`; list shows names+timestamps only.
 */
public final class CredArea {
    private CredArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "cred area not implemented yet"); }
}
