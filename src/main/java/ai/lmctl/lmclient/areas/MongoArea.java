package ai.lmctl.lmclient.areas;

/**
 * mongo area — replaces n8n's MongoDB node.
 * PINNED CLI contract (wave 5b; owner Fable; details docs/areas/mongo.md):
 *   lmclient mongo ping --url mongodb://host:27017
 *   lmclient mongo insert --url ... --db D --collection C --doc '{"json"}'
 *   lmclient mongo find --url ... --db D --collection C [--filter '{"json"}'] [--limit N]
 *   lmclient mongo delete --url ... --db D --collection C --filter '{"json"}'
 * LMCLIENT_MONGO_URL env fallback. Envelope per Envelope.java; error codes CONN / USAGE / BAD_JSON.
 * Client: mongodb-driver-sync (never the reactive driver — Netty).
 */
public final class MongoArea {
    private MongoArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "mongo area not implemented yet"); }
}
