# Standard REST & Stateless CLI Interfaces (`lmcode_std_v3` 226 Signatures)

## Summary

- `sdk.lock` pins `lmctl-ai/lmcode-java` at `a61bd716a1ccd245211ae244d6b78f505d245210` (`main-a61bd716`), and CI pins `@lmctl-ai/lmctl@0.2.482`.
- `DslHost` uses `new Registry()`, which registers all 226 canonical `lmcode_std_v3` signatures (`rest_config`, `rest_route`, `rest_serve`, `rest_stop`, `rest_cli`, `RestExchange.*`) alongside `HostApi.BINDINGS`.
- Standard REST and CLI interfaces (`RestGet`..`RestOptions`, `RestHandler`, `CliCommand`, `CliOption`) and `:param` / `{param}` route placeholders work directly inside `_lmcode_` programs executed by `lmclient --lmcode`, with `Program.callIsolated()` allowing `rest_cli(argv)` and route handlers to open and query JDBC connections without triggering registry reentry.
- `scripts/test-dsl.py` verifies `CliOption`, `CliCommand`, `RestGet` (`:param`), `rest_config("prefix", "/api")`, and `rest_cli` against an in-memory H2 database.
