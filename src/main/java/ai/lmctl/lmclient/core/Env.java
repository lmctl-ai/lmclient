package ai.lmctl.lmclient.core;

/**
 * Environment lookup for LMCLIENT_* variables. The 0.1.x binary was named lmdb and read
 * LMDB_* names; those still work as a fallback when the LMCLIENT_* name is unset.
 */
public final class Env {
    private static final String PREFIX = "LMCLIENT_";
    private static final String LEGACY_PREFIX = "LMDB_";

    private Env() {}

    public static String get(String name) {
        String value = System.getenv(name);
        if (value == null && name.startsWith(PREFIX)) value = System.getenv(LEGACY_PREFIX + name.substring(PREFIX.length()));
        return value;
    }
}
