# PostgreSQL network checks

PostgreSQL uses lmclient's JDBC commands, not a separate area command. The network
suite exercises SELECT 1, CREATE TABLE/INSERT, CSV and JSON reads, column metadata,
EXPLAIN, and JSONB/UUID values, followed by DROP cleanup.

## wiring

```sh
mvn -q -B package -DskipTests
python3 scripts/test-network.py target/lmclient-0.2.0-all.jar
# Or pass a standalone native executable instead of the jar.
```

`test.sh` includes the network suite, so the JVM mock tier runs on all five CI
platforms. No Docker is required for that tier. Existing workflow scheduling of
native network checks is unchanged; this task does not edit workflows.

The existing configured-server tier runs first, unchanged. Set
`LMCLIENT_POSTGRES_URL` to a JDBC URL and `LMCLIENT_POSTGRES_USER` /
`LMCLIENT_POSTGRES_PASSWORD` (or the generic LMCLIENT_USER/PASSWORD fallbacks)
for a real server, including Docker PostgreSQL. The SQL Server half retains its
existing LMCLIENT_MSSQL_* settings and assertions and remains real-server-only.

An additive tier starts `lmmock proto postgres` through `lmmock-helpers.py`, using
an ephemeral loopback port and a temporary JSON configuration:

```json
{"users":{"mock-user":"dummy-postgres-password"},"database":"fixture","unknownSelectError":true}
```

The same seven PostgreSQL checks and random-suffixed id/label table run against
both backends. The mock's documented table fixture handles the dynamic name;
no broad query override masks missing behavior. Mock SQL is sent through temporary
UTF-8 files to preserve JSON/identifier quotes on Windows; assertions are identical. Dummy credentials enter the
client only via environment variables. Child diagnostics remain suppressed,
and the shared context manager closes the mock and removes temporary files.

The helper pins lmmock v0.1.11 or newer. `LMMOCK_BIN` overrides binary selection;
otherwise PATH is searched, followed by checksum-verified release acquisition.
A locally installed older binary must be overridden with a compatible release.
CI sets `LMMOCK_REQUIRED=1`, turning acquisition failures into errors. Locally,
an unavailable mock prints SKIP and exits 0 **after** configured-server checks.
Force that path with `LMMOCK_BIN=/nonexistent/lmmock LMMOCK_REQUIRED=0`.

## Fidelity limits

The mock verifies JDBC/wire integration, result formats, typed values and the
specific id/label fixture. It is not evidence of general SQL semantics. Query
planning, arbitrary SQL, constraints, transactions/rollback, TLS/SCRAM, COPY,
replication and cancellation require real PostgreSQL and remain Docker/real-server
concerns. No existing assertion is weakened or removed. The seven current
PostgreSQL checks are all supported by the mock; SQL Server is not mocked.

## Verification

Local JVM build passed. With Docker PostgreSQL 17.6 and released lmmock v0.1.11,
the full suite reported `postgres: PASS` and `postgres lmmock: PASS 7 checks`.
The forced optional skip still passed real PostgreSQL before exiting 0; strict
`LMMOCK_REQUIRED=1` correctly failed acquisition with a nonexistent binary.
SQL Server was unconfigured and skipped. No mock fixes or assertion reductions
were needed. Windows/macOS and native execution remain for CI verification.
