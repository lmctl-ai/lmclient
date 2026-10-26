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

[Release CI run 40146444361](https://github.com/lmctl-ai/lmdb/actions/runs/40146444361)
also passed every native platform, the server integration job and publication.
[v0.1.0](https://github.com/lmctl-ai/lmdb/releases/tag/v0.1.0) publishes five raw
executables and SHA256SUMS. GitHub's SHA-256 digest for every executable matches
the manifest. Both Linux downloads were independently hashed and checked for
glibc-only linkage; the downloaded x64 executable passed all 40 CLI checks.

| Platform | Executable bytes |
| --- | ---: |
| linux-x64 | 128,715,632 |
| linux-arm64 | 122,292,936 |
| macos-arm64 | 357,248,264 |
| macos-x64 | 356,381,264 |
| windows-x64 | 358,084,608 |

Post-release verification used lmctl 0.2.417 with an empty LMSCRIPT_TOOL_CACHE
and an isolated LMCTL_HOME. No lmdb executable was on PATH. Running
`lmctl https://raw.githubusercontent.com/lmctl-ai/lmdb/main/examples/sqlite_sales_trend.lms`
installed the latest release: the install record reports v0.1.0 and the
executable reports `lmdb 0.1.0`. Its SHA-256 is
`7e0624153bb5447a4780ea2d68156fcb69136fd15b117ca5b68bee769eb2f05f`.
All 14 README raw-URL autoruns passed in separate empty directories and produced
the expected 900 by 560 PNG images, each smaller than 300 KB.

Intentional limits: custom JDBC jars require JVM mode; the native driver set is
fixed at compilation. Memory limits bound managed allocations, not total RSS.
No unresolved release blocker remained after these checks.
