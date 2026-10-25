# Validation of the initial release

The initial implementation uses lmcode-java v0.1.0, pinned in sdk.lock, and
compiler @lmctl-ai/lmctl 0.2.369 in CI. The bundled drivers and native source
pins are recorded in deps.lock and THIRD_PARTY_NOTICES.

Local Linux verification completed before the release gate:

- Three JDBC core suites on the JVM: generic core, H2, and multiple drivers.
- 40 CLI checks on both JVM and standalone native executable.
- 22 DSL checks on both JVM and native executable, including corrupted bytecode,
  schema mismatch, dry run, SQL/export/metadata/diff, transaction rollback,
  handle bounds and memory exhaustion.
- Native DSL execution under a 6 GiB virtual-address-space limit, including
  default-budget memory exhaustion with a controlled error.
- All 14 self-executing examples using the native host in empty directories;
  every resulting PNG is 900 by 560 pixels and smaller than 300 KB.
- Actual PostgreSQL and SQL Server native queries against disposable local
  containers, including PostgreSQL JSON/UUID and SQL Server XML values.
- Linux ELF linkage inspection and eight checker regression cases: glibc only,
  with no symbol version newer than 2.35 and no shared GCC/C++ runtime.
- Gallery visual review scored 97; inventory and budget bar charts start at zero.

CI additionally builds and tests linux-x64, linux-arm64, macos-arm64,
macos-x64 and windows-x64. Tests run a copy of the native executable without
adjacent build libraries. A subsequent Linux integration job exercises real
PostgreSQL and SQL Server services. The release job requires all these jobs.

All five platform jobs and the PostgreSQL/SQL Server integration job passed in
[main CI run 40145771721](https://github.com/lmctl-ai/lmdb/actions/runs/40145771721),
for implementation commit 48c2857005aa827a047e4b31cacb2efb6b86a45d.
Release and fresh-install results will be appended after publication.
