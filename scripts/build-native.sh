#!/usr/bin/env sh
set -eu

if ! command -v native-image >/dev/null 2>&1 && ! command -v native-image.cmd >/dev/null 2>&1; then
  printf '%s\n' 'native-image is required (install GraalVM for Java 22 or newer)' >&2
  exit 2
fi

# DuckDB's native-image integration requires JDK 22 or newer. The project
# bytecode target remains Java 21; GraalVM is only the native-image compiler.
JAVA_MAJOR=$(java -version 2>&1 | sed -n 's/.*version "\([0-9][0-9]*\).*/\1/p' | head -n 1)
case "$JAVA_MAJOR" in
  ''|[0-9]|1[0-9]|20|21) printf '%s\n' 'GraalVM native-image requires JDK 22 or newer for DuckDB' >&2; exit 2 ;;
esac

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ "$(uname -s)" = Linux ]; then
  timeout 900 scripts/build-sqlite.sh
  timeout 1800 scripts/build-duckdb.sh
  LMDB_STATIC_LIBDIR=$(dirname "$(c++ -print-file-name=libstdc++.a)")
  export LMDB_STATIC_LIBDIR
fi
mvn -q -Pnative -DskipTests package
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    if ! mt.exe -nologo '-inputresource:target/lmdb.exe;#1' -manifest scripts/windows-utf8.manifest -out:target/lmdb-merged.manifest; then
      cp scripts/windows-utf8.manifest target/lmdb-merged.manifest
    fi
    mt.exe -nologo -manifest target/lmdb-merged.manifest '-outputresource:target/lmdb.exe;#1'
    ;;
esac
