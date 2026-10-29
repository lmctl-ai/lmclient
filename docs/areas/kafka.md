# Kafka native-image spike

Branch-only experiment: `spike/kafka`. No Kafka area is registered and this
branch is not intended to merge unchanged into main.

## wiring

- Dependency: `org.apache.kafka:kafka-clients:3.9.1` (branch POM only).
- Entry point: `ai.lmctl.lmclient.spike.KafkaSpike`.
- JVM build: `mvn -q -B package -DskipTests`.
- JVM live gate: `python3 scripts/test-kafka-spike.py target/lmclient-0.2.0-all.jar`.
- Native gate: `python3 scripts/test-kafka-spike.py target/kafka-spike`.
- Broker: `apache/kafka:3.9.1`, default single-node KRaft, port 9092.
  The script starts `lmclient-kafka` and always removes it.
- CI: dispatch `ci.yml` on `spike/kafka`. Branch-only jobs build a native
  executable with **KafkaSpike as the entry point**, ensuring producer and
  consumer code is reachable. Merely adding Kafka to the normal unused
  classpath would not test native compatibility.
- Five native targets: Linux x64/arm64, macOS x64/arm64, Windows x64.
  All construct a real producer and consumer; Linux also performs the live
  produce/consume round-trip. Other normal CI jobs are skipped only on this
  spike branch, avoiding unrelated JDBC engine-build gates.
- Initial native command: `native-image --no-fallback -J-Xmx4g
  -H:NumberOfThreads=2 -cp target/lmclient-0.2.0-all.jar
  ai.lmctl.lmclient.spike.KafkaSpike target/kafka-spike`.

The test uses configured serializer/deserializer **class names**, default Kafka
metrics behavior, a unique topic/group, explicit delivery/API deadlines,
and UTF-8 payload comparison. It uses no credentials. TLS/SASL, alternate
partition assignors, interceptors, compression, transactions, and production
broker failover are outside this small gate.

## Verdict

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


### Single Kafka metadata-fix round

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

### Final evidence and recommendation

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
