#!/usr/bin/env bash
set -euo pipefail

# Build the SQLite JDBC JNI objects as a static archive for the native-image
# feature. The Java driver source and SQLite amalgamation are independently
# pinned; no generated or third-party source is committed to this repository.
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
run() { timeout "${LMDB_BUILD_TIMEOUT_SECONDS:-300}" "$@"; }

SQLITE_JDBC_TAG=3.50.3.0
SQLITE_JDBC_COMMIT=4781e381921a348fa2e533d0c43767525374b26d
SQLITE_AMALG_VERSION=3500300
SQLITE_AMALG_SHA256=9ad6d16cbc1df7cd55c8b55127c82a9bca5e9f287818de6dc87e04e73599d754
SOURCE=${LMDB_SQLITE_SOURCE:-third_party/sqlite-jdbc}
BUILD=${LMDB_SQLITE_BUILD:-target/sqlite-static-jni}
OUT=target/static-jni/libsqlitejdbc.a
fingerprint="$SQLITE_JDBC_COMMIT:$SQLITE_AMALG_SHA256:$(sha256sum "$ROOT/scripts/build-sqlite.sh" | cut -d ' ' -f 1)"
if [[ -s "$OUT" && -f target/static-jni/sqlite.pin && "$(cat target/static-jni/sqlite.pin)" == "$fingerprint" ]]; then
  echo 'verified cached SQLite static JNI archive'
  exit 0
fi
mkdir -p third_party target/static-jni "$BUILD"

if [[ ! -d "$SOURCE/.git" ]]; then
  run git clone --depth 1 --branch "$SQLITE_JDBC_TAG" https://github.com/xerial/sqlite-jdbc.git "$SOURCE"
fi
run git -C "$SOURCE" fetch --depth 1 origin "$SQLITE_JDBC_COMMIT"
run git -C "$SOURCE" checkout --detach "$SQLITE_JDBC_COMMIT"
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$SQLITE_JDBC_COMMIT" ]] || { echo 'sqlite-jdbc commit verification failed' >&2; exit 2; }

ZIP="$BUILD/sqlite-amalgamation-${SQLITE_AMALG_VERSION}.zip"
if [[ ! -f "$ZIP" ]]; then
  run curl --fail --location --retry 3 --output "$ZIP" "https://www.sqlite.org/2025/sqlite-amalgamation-${SQLITE_AMALG_VERSION}.zip"
fi
echo "$SQLITE_AMALG_SHA256  $ZIP" | sha256sum --check --status
AMALG="$BUILD/sqlite-amalgamation-${SQLITE_AMALG_VERSION}"
if [[ ! -f "$AMALG/sqlite3.c" ]]; then
  run unzip -q -o "$ZIP" -d "$BUILD"
fi

JAVA_BIN=${JAVA_HOME:-}
if [[ -z "$JAVA_BIN" ]]; then JAVA_BIN=$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")"); fi
JAVAC="$JAVA_BIN/bin/javac"
[[ -x "$JAVAC" ]] || { echo 'JDK javac is required' >&2; exit 2; }
JAVA_INCLUDE="$JAVA_BIN/include"
case "$(uname -s)" in
  Linux) JAVA_PLATFORM_INCLUDE="$JAVA_INCLUDE/linux"; CC=${CC:-cc}; AR=${AR:-ar} ;;
  Darwin) JAVA_PLATFORM_INCLUDE="$JAVA_INCLUDE/darwin"; CC=${CC:-cc}; AR=${AR:-ar} ;;
  *) echo 'build-sqlite.sh supports Linux and macOS hosts; cross builds use the native CI job' >&2; exit 2 ;;
esac
[[ -f "$JAVA_PLATFORM_INCLUDE/jni_md.h" ]] || { echo "missing JNI headers: $JAVA_PLATFORM_INCLUDE" >&2; exit 2; }

CLASSES="$BUILD/classes"
HEADERS="$BUILD/headers"
mkdir -p "$CLASSES" "$HEADERS" "$BUILD/work"
SQLITE_JAR=${LMDB_SQLITE_JAR:-$HOME/.m2/repository/org/xerial/sqlite-jdbc/$SQLITE_JDBC_TAG/sqlite-jdbc-$SQLITE_JDBC_TAG.jar}
[[ -f "$SQLITE_JAR" ]] || { echo "sqlite-jdbc jar is required for JNI header generation: $SQLITE_JAR" >&2; exit 2; }
run "$JAVAC" -h "$HEADERS" -d "$CLASSES" -cp "$SQLITE_JAR" "$SOURCE/src/main/java/org/sqlite/core/NativeDB.java"
cp "$HEADERS/org_sqlite_core_NativeDB.h" "$HEADERS/NativeDB.h"

# Match xerial's amalgamation preparation: extension functions are compiled
# into SQLite, and sqlite3_api is made a real pointer for the core build.
sed 's/sqlite3_api;/sqlite3_api = 0;/g' "$AMALG/sqlite3.c" > "$BUILD/work/sqlite3.c"
cat "$SOURCE/src/main/ext/extension-functions.c" >> "$BUILD/work/sqlite3.c"
COMMON=(-fPIC -O2 -I"$AMALG" -I"$SOURCE/lib/inc_linux" -I"$JAVA_INCLUDE" -I"$JAVA_PLATFORM_INCLUDE" -I"$HEADERS")
DEFS=(-DSQLITE_ENABLE_LOAD_EXTENSION=1 -DSQLITE_HAVE_ISNAN -DHAVE_USLEEP=1 -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_CORE -DSQLITE_ENABLE_FTS3 -DSQLITE_ENABLE_FTS3_PARENTHESIS -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_STAT4 -DSQLITE_ENABLE_DBSTAT_VTAB -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_THREADSAFE=1 -DSQLITE_DEFAULT_MEMSTATUS=0 -DSQLITE_DEFAULT_FILE_PERMISSIONS=0666 -DSQLITE_MAX_VARIABLE_NUMBER=250000 -DSQLITE_MAX_MMAP_SIZE=1099511627776 -DSQLITE_MAX_LENGTH=2147483647 -DSQLITE_MAX_COLUMN=32767 -DSQLITE_MAX_SQL_LENGTH=1073741824 -DSQLITE_MAX_FUNCTION_ARG=127 -DSQLITE_MAX_ATTACHED=125 -DSQLITE_MAX_PAGE_COUNT=4294967294 -DSQLITE_DISABLE_PAGECACHE_OVERFLOW_STATS)
run "$CC" -c "${COMMON[@]}" "${DEFS[@]}" "$BUILD/work/sqlite3.c" -o "$BUILD/work/sqlite3.o"
# Static native-image registration calls a namespaced loader so multiple JDBC
# archives can coexist without colliding on JNI_OnLoad.
sed -e 's/JNI_OnLoad(/JNI_OnLoad_sqlitejdbc(/g' -e 's/JNI_OnUnload(/JNI_OnUnload_sqlitejdbc(/g' "$SOURCE/src/main/java/org/sqlite/core/NativeDB.c" > "$BUILD/work/NativeDB.c"
run "$CC" -c "${COMMON[@]}" "$BUILD/work/NativeDB.c" -o "$BUILD/work/NativeDB.o"
run "$AR" rcs "$OUT" "$BUILD/work/sqlite3.o" "$BUILD/work/NativeDB.o"

SYMBOLS=$(nm -g "$OUT")
grep -Eq '(^| )JNI_OnLoad_sqlitejdbc$' <<<"$SYMBOLS" || { echo 'static SQLite archive lacks JNI_OnLoad_sqlitejdbc' >&2; exit 2; }
grep -Eq 'Java_org_sqlite_core_NativeDB__1open_1utf8' <<<"$SYMBOLS" || { echo 'static SQLite archive lacks NativeDB JNI entry point' >&2; exit 2; }
echo "SQLite JDBC static JNI archive: $OUT"
echo "xerial commit: $SQLITE_JDBC_COMMIT"
echo "SQLite amalgamation: $SQLITE_AMALG_VERSION ($SQLITE_AMALG_SHA256)"
echo "JNI symbols: JNI_OnLoad_sqlitejdbc, Java_org_sqlite_core_NativeDB__1open_1utf8"
printf '%s\n' "$fingerprint" > target/static-jni/sqlite.pin
