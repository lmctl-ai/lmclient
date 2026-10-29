# Protocol areas (2026-10-29)

Wave 5 turned lmclient from a JDBC client into a general protocol client.
`Main.run()` dispatches `args[0]` through `areas.Areas.REGISTRY` to
`areas.<Name>Area.run(String[] rest)`; the JDBC path is unchanged for every
other first argument.

## Why areas

n8n's connector catalogue splits into HTTP-shaped nodes (covered by lmconn's
`http request` plus credentials), AWS (sibling repository lmaws), SQL (this
repository's JDBC core) and a tail of binary protocols that no HTTP client can
reach: Redis, SMTP/IMAP, AMQP, MQTT, MongoDB. Those five became areas. One
native executable per platform replaces five n8n nodes and their runtime,
and lmscript drives them through `system()` with the same envelope it already
parses for lmconn.

## Conventions every area follows

- One JSON object on stdout per run: `{"ok":true,"result":...}` or
  `{"ok":false,"error":{"code","message"}}` (`areas.Envelope`). Human text
  goes to stderr, and in practice stderr stays empty on success.
- Exit codes 0 ok, 2 usage, 3 runtime. Malformed input such as a bad
  `--doc` JSON is a usage-class error (exit 2) even when its code is more
  specific (`BAD_JSON`).
- Connection by `--url` or `LMCLIENT_<AREA>_URL`; passwords from
  `LMCLIENT_USER` / `LMCLIENT_PASSWORD` or `--credentials-file` (Java
  properties, the existing `Credentials` pattern). URL-embedded credentials
  are accepted where the protocol defines them but never echoed; error
  messages are reduced to the root cause and scrubbed.
- A timeout on every network operation, default about 10 s, `--timeout MS`.
- `docs/areas/<area>.md` with a `## wiring` section is the contract between
  an area author and the wiring owner: Maven coordinates, test invocation,
  CI service container, native-image needs.
- `scripts/test-<area>.py` runs usage checks always and live checks against
  a throwaway docker container (or a CI-provided `LMCLIENT_<AREA>_URL`),
  skipping live checks with a clear message when docker is absent. `test.sh`
  runs all five after `test-cli.py`.

## Native-friendly client choices

The release is a GraalVM native image, so clients were chosen for plain
sockets and no runtime code generation:

| Area | Client | Rejected alternative |
|---|---|---|
| redis | Jedis 5.2.0 | Lettuce (Netty, reactive types) |
| mail | Angus Mail 2.0.3 on Jakarta Mail API 2.1.3, direct SMTP/IMAP constructors | provider discovery through reflection |
| queue | amqp-client 5.22.0 (blocking sockets) | Spring AMQP, reactor-rabbitmq |
| mqtt | Paho mqttv3 1.2.5 (socket network module, in-memory persistence) | HiveMQ client (Netty) |
| mongo | mongodb-driver-sync 5.2.1 with the `Document` API | mongodb-driver-reactivestreams (Netty) |

Jedis mandates `slf4j-api` 1.7, which made the MongoDB driver detect SLF4J
and print "no StaticLoggerBinder" warnings on stderr. `org.slf4j:slf4j-nop`
1.7.36 is on the classpath so every area stays silent. Native verification
still belongs to the manually dispatched CI build; locally only `mvn verify`
on the JVM is possible.

## A shared-checkout lesson

Four agents committed from one working tree. A `git pull --rebase
--autostash` by one agent reset the files another agent had just edited but
not yet committed, and a commit made a moment later recorded the stub
versions. The symptom was a commit whose message promised files it did not
contain. The fix was to re-apply the work and verify `git show --stat HEAD`
and the pushed file contents before reporting. Rule of thumb for shared
trees: commit as soon as a file compiles, and check what the commit actually
recorded.
