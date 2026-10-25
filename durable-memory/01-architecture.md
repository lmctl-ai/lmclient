# Architecture and release gates

lmdb is an MIT-licensed Java 21 JDBC client and lmcode host. Maven pins five
bundled drivers: PostgreSQL, SQLite, H2, DuckDB and Microsoft SQL Server. No GPL
MySQL or LGPL MariaDB JDBC driver is bundled. Optional jars require JVM mode or
a custom native build because GraalVM's closed-world executable cannot load
arbitrary new Java classes at runtime.

The CLI uses JDBC directly. HostApi is the single declaration catalog for the
format-2 schema and callback signatures. The released lmcode-java v0.1.0 SDK is
pinned at 7c19df8f6394b402ef23b5a5868019468edd17b5 by sdk.lock. SQL values and metadata are
bounded; credentials come from environment variables or UTF-8 properties files.
Exceptions displayed to users never contain raw driver messages or SQL.

Build with `mvn -q verify`; `test.sh` checks versions, JVM behavior, examples and
gallery artifacts. CI uses GraalVM Community JDK 25; bytecode targets Java 21.
CI is authoritative for five platforms, including actual PostgreSQL and SQL
Server queries in addition to embedded SQLite, H2 and DuckDB tests.

Release gate: all five native binaries must pass tests before tagging v0.1.0.
Linux permits dynamic glibc with symbol versions no newer than 2.35; GCC runtimes and all other third-party
dependencies must be static. This rule covers embedded/extracted JDBC JNI
libraries as well as the main executable. Linux links custom SQLite and DuckDB
JNI archives and the GCC runtimes statically. The JNI initialization calls are
direct native-image C functions because GraalVM's built-in JNI initializer map
does not include these third-party libraries. On macOS and Windows, the embedded
upstream JDBC JNI resources extract privately when loaded.

LMDB_MAX_MEMORY_MB defaults to 4096. The launcher restarts once when needed to
cap the immutable Java heap at 75% of that budget. Each embedded native engine
gets at most one eighth, with at most two simultaneous SQLite/DuckDB connections.
This bounds managed allocations rather than total RSS. Native executables reserve
4 GiB of address space so hosts probing them under a 6 GiB limit can start.
H2 GUI reflection entries are excluded, and a build-time reachability guard
rejects java.awt.Toolkit so the executable does not require AWT sidecar libraries.

Examples create embedded databases from inline SQL, export CSV, then render with
lmplot or lmdraw. They save and run their own bytecode so `lmctl autorun RAW_URL`
in an empty directory produces the picture. Release and fresh-install evidence
is recorded in 02-validation.md.
