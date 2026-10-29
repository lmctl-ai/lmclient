# mongo area

Replaces n8n's MongoDB node: one native executable, one JSON envelope per
run, no server-side driver install. Owner: Fable (wave 5b).

## wiring

- Maven: `org.mongodb:mongodb-driver-sync:5.2.1` (brings `org.mongodb:bson`
  and `org.mongodb:mongodb-driver-core` 5.2.1). The sync driver uses plain
  sockets; never the reactive driver, which pulls Netty.
- Test: `python3 scripts/test-mongo.py target/lmclient-0.2.0-all.jar` (also
  accepts a native executable). Usage checks always run; live checks start a
  throwaway `mongo:7` container on an ephemeral loopback port and remove it,
  or use `LMCLIENT_MONGO_URL` when set (CI service container). Live checks are
  skipped with a message when docker is unavailable.
- CI service: `mongo:7`, TCP 27017, no auth; set
  `LMCLIENT_MONGO_URL=mongodb://127.0.0.1:27017` for the test script.
- Native: the Document-based API needs no application reflection entries;
  optional driver features (compression, DNS SRV, snappy/zstd) probe classes
  with `Class.forName` in try/catch and degrade when absent. Native
  verification belongs to the manually triggered CI build.
- Logging: the driver logs through SLF4J when present. `jedis` (redis area)
  mandates `slf4j-api` 1.7.36, so pom.xml adds `org.slf4j:slf4j-nop:1.7.36`
  to keep stderr silent for every area.
- Example: `lmscript examples/mongo_demo.lms [binary] [url]` (skips cleanly
  when the binary or server is missing).

## Commands

```
lmclient mongo ping   --url mongodb://host:27017
lmclient mongo insert --url ... --db D --collection C --doc '{"json"}'
lmclient mongo find   --url ... --db D --collection C [--filter '{"json"}'] [--limit N]
lmclient mongo delete --url ... --db D --collection C --filter '{"json"}'
```

Common flags: `--timeout MS` (default 10000; applies to server selection,
connect, read and the find cursor), `--credentials-file FILE` (Java
properties with `user` and `password`). `LMCLIENT_MONGO_URL` is the URL
fallback; `LMCLIENT_USER` / `LMCLIENT_PASSWORD` supply credentials, which are
authenticated against the URL's database or `admin`. A URL may embed
`user:password@` (standard MongoDB form) but prefer the environment or the
file so secrets stay out of process arguments; URL credentials are never
echoed.

| Command | Result |
|---|---|
| `ping` | `{"pong":true}` |
| `insert` | `{"insertedId":"<hex ObjectId or the supplied _id>"}` |
| `find` | `{"count":N,"docs":[...]}`; `_id` is a string; other BSON types use relaxed extended JSON; `--limit` defaults to 100, maximum 10000 |
| `delete` | `{"deleted":N}` (`deleteMany`; `--filter` is mandatory, `{}` empties the collection on purpose) |

Errors: `{"ok":false,"error":{"code","message"}}`.

| Code | Exit | When |
|---|---|---|
| `USAGE` | 2 | missing or unknown flags, bad `--limit`/`--timeout`, non-mongodb URL |
| `BAD_JSON` | 2 | `--doc` or `--filter` is not a JSON object |
| `CONN` | 3 | cannot reach or authenticate (`host: Connection refused (timed out waiting for a server)`) |
| `SERVER` | 3 | the server rejected the command or write (`(BadValue): unknown top level operator: $bogus`) |

Messages are reduced to the root cause, with the password and any
`user:password@` URL part redacted. Nothing is written to stderr.

## Scope

v1 covers n8n's MongoDB node operations insert, find and delete plus a
connectivity ping. Update, aggregate, bulk writes and index management are
out of scope for this wave; they fit the same envelope and flag style.
