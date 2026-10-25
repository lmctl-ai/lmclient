# Native JDBC resource size

The v0.1.0 macOS/Windows images included foreign-platform JDBC native resources.
The resource configuration includes all SQLite and DuckDB natives; only Linux
previously had an exclusion, because it uses statically linked JNI archives.
The native compiler already defaults to no generated debug information and
enabled debug stripping. This change retains the existing optimization settings.

The shaded JAR contains 282,735,312 bytes under the native-resource prefixes.
The target filters exclude 173,986,880 bytes on macOS ARM64, 173,835,300 bytes on
macOS x64, and 246,665,424 bytes on Windows x64. The JVM JAR remains portable.

`scripts/native_resources.py` creates the native-image exclusion argument for
the actual build platform. `scripts/test-native-resources.py` checks every
target against the actual shaded JAR. Native CI also inspects GraalVM's
embedded-resources.json: no foreign-platform JNI resource may be retained,
and macOS/Windows must contain exactly their DuckDB and SQLite libraries.
This catches accidental reintroduction through third-party reachability metadata.
Xerial's feature explicitly adds its host SQLite library through
RuntimeResourceAccess, bypassing regex exclusions. Linux therefore retains that
small unused host resource, as v0.1.0 already did; JdbcSubstitutions initializes
the statically linked engine and never extracts or loads the shared copy.
Graal interprets a colon in an exclusion as a module:pattern selector, so these
regexes must avoid noncapturing groups such as `(?:...)`. The filter regression
checks enforce that restriction in addition to testing retained resource names.
The filter is generated into classpath native-image.properties before packaging.
Do not replace it with an @argument-file build argument: Maven already wraps
Windows arguments in a file, and native-image does not expand nested files.
GraalVM 25 tests exclusions against both a resource name and that name plus a
trailing slash. The retention lookahead must protect both variants; the
JAR-based regression checks simulate this behavior. Otherwise the target's
DuckDB resource is removed even though its normal filename matches the keep list.

DuckDB currently ships one universal macOS resource, which its loader expects
as libduckdb_java.so_osx_universal. SQLite ships separate Mac/aarch64 and
Mac/x86_64 resources. Windows uses DuckDB's windows_amd64 resource and SQLite's
Windows/x86_64/sqlitejdbc.dll. Do not remove these retained resources or change
their paths without testing the upstream loaders.

[Main CI run 40149496805](https://github.com/lmctl-ai/lmdb/actions/runs/40149496805)
passed all five native targets, including embedded-resource inventories, five
driver probes, CLI/DSL checks and all 14 examples. PostgreSQL and SQL Server
integration also passed. The implementation is commit 10283c15906a73de9cae9c563bc8548cb6c0d523.

The measured CI executables qualified the release; published v0.1.1 macOS and
Windows asset sizes match those candidates exactly:

| Platform | v0.1.0 bytes | v0.1.1 bytes | Reduction |
| --- | ---: | ---: | ---: |
| macos-arm64 | 357,248,264 | 181,560,584 | 49.18% |
| macos-x64 | 356,381,264 | 182,252,112 | 48.86% |
| windows-x64 | 358,084,608 | 110,948,352 | 69.02% |

The standalone local Linux image remained exactly 129,633,136 bytes with the
same Oracle GraalVM toolchain as the prior local build. It passed 40 CLI checks,
22 DSL checks under a 6 GiB address-space limit, all 14 examples and ELF linkage
inspection. Published Linux images use the CI Community toolchain instead.

[Release CI run 40150052050](https://github.com/lmctl-ai/lmdb/actions/runs/40150052050)
passed all five native targets, PostgreSQL/SQL Server integration and
[v0.1.1 publication](https://github.com/lmctl-ai/lmdb/releases/tag/v0.1.1).
All five executable SHA-256 digests match SHA256SUMS. Both downloaded Linux
executables pass the glibc-only linkage audit; the x64 download passed all 40 CLI
checks. Published Linux x64 stays at 128,715,632 bytes; ARM64 changes from
122,292,936 to 122,227,400 bytes.

Fresh-cache verification used lmctl 0.2.417, an isolated LMCTL_HOME and an empty
LMSCRIPT_TOOL_CACHE, with no lmdb executable on PATH. The first README autorun
installed v0.1.1 via @latest; its executable reports `lmdb 0.1.1` and matches the
published checksum. All 14 README raw-URL autoruns passed in separate empty
directories and wrote the expected 900 by 560 PNG images, each below 300 KB.
No driver was removed, compiler optimization settings are unchanged, and no
known release blocker remains. macOS still retains DuckDB's universal library.
