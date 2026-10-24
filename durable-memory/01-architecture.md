# Architecture and release gates

lmdb is an MIT-licensed Java 21 JDBC client and lmcode host. Maven pins five
bundled drivers: PostgreSQL, SQLite, H2, DuckDB and Microsoft SQL Server. No GPL
MySQL or LGPL MariaDB JDBC driver is bundled. Optional jars require JVM mode or
a custom native build because GraalVM's closed-world executable cannot load
arbitrary new Java classes at runtime.

The CLI uses JDBC directly. HostApi is the single declaration catalog for the
format-2 schema and callback signatures. The lmcode-java SDK is integrated only
after its first release and is pinned by sdk.lock. SQL values and metadata are
bounded; credentials come from environment variables or UTF-8 properties files.
Exceptions displayed to users never contain raw driver messages or SQL.

Build with `mvn -q verify`; `test.sh` checks versions, JVM behavior, examples and
gallery artifacts. `scripts/build-native.sh` needs GraalVM JDK 22 or newer due
to DuckDB's JNI implementation. CI is authoritative for five platforms.

Release gate: all five native binaries must pass tests before tagging v0.1.0.
Linux permits dynamic glibc >= 2.35 only; GCC runtimes and all other third-party
dependencies must be static. This rule covers embedded/extracted JDBC JNI
libraries as well as the main executable. The upstream DuckDB Linux JNI library
requires a custom build to remove shared libstdc++ and libgcc dependencies.

Examples create embedded databases from inline SQL, export CSV, then render with
lmplot or lmdraw. They save and run their own bytecode so `lmctl autorun RAW_URL`
in an empty directory produces the picture. Release and fresh-install evidence
will be recorded after those gates pass.
