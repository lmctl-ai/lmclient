# Family credential commands

`lmclient cred` uses the existing `CredStore` SQLite schema, shared with lmconn.
No additional dependencies or native reflection configuration are required.

## wiring

Build: `mvn -q -B package -DskipTests`.

Test: `python3 scripts/test-cred.py target/lmclient-0.2.0-all.jar`.
The script also accepts a native executable, or defaults to the versioned jar.
It uses a fresh temporary `LMCLIENT_DB`; it needs no containers or network.
Java closes database handles per operation; the Node interoperability checks
explicitly close their cached handle before the temporary directory is removed.

For interoperability checks, install Node with `node:sqlite` support (>=22.5)
and check out lmconn at `~/lmworkflow/lmconn`, or set `LMCONN_CREDS_MODULE` to
its `src/creds.js`. When Node or that checkout is absent, only the cross-tool
checks are skipped, with an explicit message. Both directions must pass when
those prerequisites are present.

## Commands

- `cred set SERVICE FIELD (--value V | --env VAR | --stdin)` requires exactly
  one source. Empty values are allowed; an absent environment variable is not.
  Stdin is read completely as UTF-8, preserving whitespace and trailing newlines.
  `--value` emits an argv-exposure warning to stderr. Prefer env or stdin.
  Result: `{"service":"...","field":"...","stored":true}`.
- `cred get SERVICE FIELD` returns names and `set:true|false` without values.
  `--reveal` adds `value` for piping, and returns `NOT_FOUND` when missing.
- `cred list` returns an array of `{service,field,updated_at}` in name order.
- `cred delete SERVICE FIELD` returns `{deleted:true|false}`.
- `cred path` returns `{path:"..."}` without opening the database.

Every invocation emits one JSON envelope. Secret values appear only with
`get --reveal`. Usage errors return `USAGE`; unexpected storage or input failures
return a generic `CREDENTIAL_ERROR` without underlying exception details.

Path resolution is delegated unchanged to CredStore: `LMCLIENT_DB` (legacy
`LMDB_DB` alias), then `LMCONN_DB`, then `~/.lmconn/creds.db`, with the existing
legacy `~/.lmconnectors/creds.db` fallback. The tests always use explicit paths.

## Compatibility

Command parsing, result shapes, redaction, and missing-value behavior match
lmconn. Runtime errors use lmclient's required exit **3**, versus lmconn's **1**;
usage remains exit **2** and success exit **0**. Timestamp spelling comes from
CredStore (`Instant` ISO format), while JS uses millisecond ISO formatting; both
read each other's stored timestamps and values without conversion.
