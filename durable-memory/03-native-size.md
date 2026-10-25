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

DuckDB currently ships one universal macOS resource, which its loader expects
as libduckdb_java.so_osx_universal. SQLite ships separate Mac/aarch64 and
Mac/x86_64 resources. Windows uses DuckDB's windows_amd64 resource and SQLite's
Windows/x86_64/sqlitejdbc.dll. Do not remove these retained resources or change
their paths without testing the upstream loaders.

Release sizes and validation are recorded after the five-platform build.
