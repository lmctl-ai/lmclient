# MQTT

`lmclient mqtt pub --url tcp://localhost:1883 --topic demo --message hello --qos 1`
publishes a UTF-8 message. `mqtt sub --topic demo --limit 3 --timeout 10000`
subscribes and returns `{"messages":[{"topic":"demo","payload":"hello"},...]}`.
Subscriptions must be active before publishing; messages are not retained.
A timeout returns the messages collected, including an empty list. `mqtt ping`
connects to the broker. QoS 0, 1, and 2 are supported; default is 0.

Connection URL: `--url` or `LMCLIENT_MQTT_URL`. Use `tcp://` or `ssl://`.
Authentication uses `LMCLIENT_USER`/`LMCLIENT_PASSWORD` or `--credentials-file`
with `user` and `password` properties; environment values override the file.
All commands accept `--timeout` in milliseconds (default 10000). Limits must
be 1..10000. Errors are sanitized `CONN` (exit 3) or `USAGE` (exit 2).
Each invocation uses a unique client ID and an in-memory, clean session.
There is no persistent-session, retained-publication, or MQTT 5 API.

## wiring

- Maven: `org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5`.
- Test: `python3 scripts/test-mqtt.py target/lmclient-0.2.0-all.jar` (also accepts a native executable).
- The additive lmmock tier runs before Docker detection on all platforms using
  the shared pinned release (v0.1.10 or newer). `LMMOCK_BIN` overrides the binary;
  PATH and checksum-verified download are fallbacks. Missing binaries skip
  locally, while `LMMOCK_REQUIRED=1` makes acquisition failures fatal in CI.
- `lmmock proto mqtt` readiness uses `mqtt://`; the tier translates it to the
  client's `tcp://`. It checks env URL fallback, ordered QoS 0/1/2 publication,
  Unicode/quotes/newlines and an empty subscription deadline. A transparent
  loopback relay observes the subscriber's actual SUBACK before publication;
  no broker logging or fixed startup sleep is required.
- A second broker receives temporary JSON config
  `{"users":{"tester":"<dummy password>"}}` and checks missing/wrong credentials,
  environment credentials and a credentials file, including secret redaction.
- The existing `eclipse-mosquitto:2` Docker tier remains unchanged, with anonymous
  access, an ephemeral loopback host port and container cleanup. It runs after
  the mock tier and skips clearly when Docker is unavailable. All existing
  live assertions also run against the mock. TLS and persistence are not
  exercised by the existing suite and are not claimed by the mock tier.
- Native: Paho uses socket network modules and in-memory persistence. Retain its ServiceLoader providers via the existing shaded services transformer. Area native-image metadata registers its reflective logger and message resource bundles. Native verification belongs to CI; local verification is JVM only.
- Example: `lmscript examples/mqtt_demo.lms` (service must be running; skips if unreachable).

## verification

JVM live suite: 19 checks passed against the container image above.
Mosquitto: an independent subscriber received QoS 0, 1, and 2 publications in order, including quotes, Unicode, and a newline. An empty subscription returned an empty list after its deadline.
The isolated JVM `mvn -q -B verify` build passed. Native-image and TLS
interoperability have not been tested locally.

Wave 8 Linux JVM validation against released lmmock v0.1.10: 13 offline checks,
10 mock checks and 6 real Mosquitto checks passed (29 total). With Docker hidden
from PATH, all 23 offline/mock checks passed before the Docker-only skip. A
forced missing `LMMOCK_BIN` skipped locally, while strict acquisition rejected
it. Windows/macOS runtime verification belongs to CI.

### Windows fixture encoding

All client envelope pipes are decoded explicitly as UTF-8. The Windows JDK
launcher processes argv using the system ANSI code page (CP_ACP), before
Java's UTF-8 output settings apply; changing Python's decoder or
`-Dfile.encoding` cannot restore characters lost at that boundary. See
[OpenJDK's Windows argument parser](https://github.com/openjdk/jdk/blob/jdk-25-ga/src/java.base/windows/native/libjli/cmdtoargs.c).
The payload command has no file-input option, so Windows round-trip fixtures
use plain ASCII argv; Unix retains Unicode, embedded quotes, and newlines.
Both mock and Docker tiers use the same platform fixture. This is a test
coverage limitation, not a claim that arbitrary Unicode argv works on Windows.
