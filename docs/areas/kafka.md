# Kafka

Plaintext Kafka producer, bounded consumer, and broker connectivity probe.

```sh
lmclient kafka ping --url localhost:9092
lmclient kafka produce --url localhost:9092 --topic events --message 'hello'
lmclient kafka consume --url localhost:9092 --topic events --limit 3 --timeout 10000
```

`--url host:port` overrides `LMCLIENT_KAFKA_URL`. A single bootstrap endpoint is
accepted (IPv6 uses `[::1]:9092`). All commands accept `--timeout` in positive
milliseconds, default 10000. Consume defaults to one message, maximum 10000.
Unknown flags, duplicate flags, invalid topics, and missing values are usage
errors (exit 2, `USAGE`). Broker failures return exit 3, `CONN`, without driver
exception details. Successful commands return one JSON envelope (exit 0).

Produce returns `{"published":true}` after broker acknowledgement (`acks=all`).
It writes partition **0** to preserve ordering across independent CLI calls.
The broker may auto-create a missing topic if configured to allow it.
Ping queries broker metadata and returns `{"connected":true}`.
Consume returns `{"messages":["value",...]}` (Kafka tombstones become JSON null).
It explicitly assigns all topic partitions and starts at their earliest retained
offsets on **every invocation**, without a consumer group or offset commits.
Kafka does not remove messages on read. Ordering is per partition; no global
ordering is promised for topics populated across multiple partitions.
It returns available messages when the read deadline expires, even if fewer than
`--limit` arrived; metadata/connection failures instead return `CONN`.

Network calls have bounded deadlines and clients close without an unbounded
flush. DNS and JVM startup may add wall time. This initial area intentionally
exposes no SASL, TLS, compression, transactions, group subscription, or offset
management settings. Credentials embedded in bootstrap URLs are rejected.

## wiring

- Dependency and deps.lock pin: `org.apache.kafka:kafka-clients:3.9.1`.
- Registry: `Areas.REGISTRY`, `KafkaArea::run`.
- JVM gate: `mvn -q -B verify`.
- Live gate: `python3 scripts/test-kafka.py target/lmclient-0.2.0-all.jar`.
  The same script accepts a native binary path. `test.sh` includes Kafka.
- Tier order: 17 offline usage/connection-timeout checks, then 10 live checks
  against released `lmmock proto kafka`, then the same 10 checks against Docker.
  The mock uses the shared `scripts/lmmock-helpers.py` acquisition/lifecycle
  harness, with `{"topics":{"roundtrip":1}}` passed through a temporary config
  file. The `kafka://` readiness URL is converted to the required host:port.
  It runs without Docker on all five CI platforms and accepts `LMMOCK_BIN` for
  an explicit binary. Missing mocks print SKIP locally; `LMMOCK_REQUIRED=1`
  makes acquisition failure fatal in CI.
- Shared live assertions cover env fallback/flag priority, partition-zero
  idempotent production with acks=all, ordered UTF-8 and empty values, earliest
  replay, and partial reads at 1500 ms. No existing live assertion is Docker-only.
  Docker additionally validates this contract against a real KRaft broker;
  persistence, replication, TLS/SASL, transactions, and group rebalancing are
  outside the current suite and are not claimed by the mock.
- Broker: `apache/kafka:3.9.1` single-node KRaft. Tests choose a local host port,
  configure the advertised address, and always remove their unique container.
  Docker unavailable: offline and lmmock checks have already run; only the
  Docker tier clearly skips. Force a local mock-acquisition skip with
  `LMMOCK_BIN=/nonexistent/lmmock LMMOCK_REQUIRED=0 python3 scripts/test-kafka.py`.
- Wave 8 local verification: the JVM area suite passed **37 checks** (17 offline,
  10 lmmock, 10 Docker); forced mock acquisition skip retained all 17 offline
  checks and exited successfully. The original 1500 ms partial-read assertion
  is unchanged. No mock bugs or assertion exclusions were needed.
- Native metadata: `src/main/resources/META-INF/native-image/ai.lmctl/lmclient-kafka/`.
  Five public-constructor registrations (StringSerializer, StringDeserializer,
  RangeAssignor, CooperativeStickyAssignor, JmxReporter) plus the
  `kafka/kafka-version.properties` resource. No substitutions.
- Local evidence: `mvn -q -B verify` passed; the live suite passed **27 checks**
  against `apache/kafka:3.9.1`. Tests exercise usage errors, safe failure
  output, timeout bounds, ping, env fallback/flag priority, three ordered
  messages, earliest-offset replay, partial results at timeout, and empty values.
- Full-family native CI is triggered by Lead; it was not dispatched for this
  promotion. The historical isolated spike evidence below is not a claim that
  the integrated area has passed full-family native CI.

## Historical native spike evidence

The `spike/kafka` branch tested a dedicated Kafka entry point. Its evidence and
limitations are retained below; the production area above supersedes its CLI.

### Spike verdict

JVM live round-trip passed against `apache/kafka:3.9.1` (UTF-8 key/payload
and offset verified; container removed). Native gates passed on all five platforms after one metadata-fix round.

The first CI dispatch (40822836520) failed before Kafka analysis with an
unrelated family-jar feature error:

```
Error: User-enabled Feature org.sqlite.nativeimage.SqliteJdbcFeature class not found.
```

The spike harness now builds a Kafka-only classpath (the two spike classes,
Kafka, SLF4J, and Kafka compression dependencies), excluding unrelated JDBC
metadata. This corrects the experiment; it is not a Kafka reflection fix.
No native build is run locally.


#### Single Kafka metadata-fix round

Run 40823047697 compiled Kafka natively on Linux x64/arm64 and macOS arm64,
but native construction failed with:

```
org.apache.kafka.common.config.ConfigException: Invalid value org.apache.kafka.common.serialization.StringSerializer for configuration key.serializer: Class org.apache.kafka.common.serialization.StringSerializer could not be found.
```

One hand-written metadata round registers public constructors for StringSerializer,
StringDeserializer, RangeAssignor, CooperativeStickyAssignor, and JmxReporter,
and includes `kafka/kafka-version.properties`. No substitutions or Kafka source
changes are used. The Windows harness also uses `native-image.cmd`; its previous
`native-image: command not found` was not a Kafka compatibility result.

#### Final evidence and recommendation

**Verdict: adopt with config**, for the tested plaintext String producer/consumer
path. No deep substitutions were needed. Keep the five constructor entries and
version resource with the dependency when integrating a production area.

[Final CI run 40823460378](https://github.com/lmctl-ai/lmclient/actions/runs/40823460378)
tested commit `5779f5b` with GraalVM Community Java 25:

| Platform | Native build | Native producer/consumer construction | Native live round-trip |
| --- | --- | --- | --- |
| Linux x64 | passed | passed | passed |
| Linux arm64 | passed | passed | passed |
| macOS x64 | passed | passed | not run |
| macOS arm64 | passed | passed | not run |
| Windows x64 | passed | passed | not run |

Local JVM verification commands:

```sh
mvn -q -B package -DskipTests
python3 scripts/test-kafka-spike.py target/lmclient-0.2.0-all.jar
```

The JVM and both Linux native tests returned `{"ok":true,"result":{"roundTrip":true,...}}`
with the exact payload `hello Kafka — UTF-8`; key and offset were also checked.
The Docker broker was removed after each live test. Every platform also passed
shaded-jar JVM client construction in CI.

The successful native executable deliberately contains only Kafka's dependency
graph plus the spike entry point and Envelope. **The full lmclient native image
has not been validated with Kafka integrated.** The initial unrelated SQLite
feature failure remains a family-build integration concern, not evidence that
Kafka itself fails. macOS/Windows network I/O, subscription/rebalancing,
TLS/SASL, compression, transactions, and failure recovery remain unverified.
Do not treat construction-only checks as live broker coverage.

The final branch was rebased onto main's subsequent GitHub-area commit; this
changes no Kafka spike code or native metadata from the tested commit. This
branch is an experiment, not a production area implementation.

Earlier evidence: [initial harness run](https://github.com/lmctl-ai/lmclient/actions/runs/40822836520)
and [missing-reflection run](https://github.com/lmctl-ai/lmclient/actions/runs/40823047697).
Exactly one Kafka metadata-fix round was applied; no further fixes are pending.
