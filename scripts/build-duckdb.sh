#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/third_party/duckdb-java"
BUILD="$ROOT/target/duckdb-java-build"
OUT="$ROOT/target/generated-resources"
COMMIT=679d526542cf9dfb24322d9d9c75641624f24bc1

[ "$(uname -s)" = Linux ] || { printf '%s\n' 'custom DuckDB JNI build currently supports Linux runners only' >&2; exit 2; }
command -v git >/dev/null 2>&1 || { printf '%s\n' 'git is required' >&2; exit 2; }
command -v cmake >/dev/null 2>&1 || { printf '%s\n' 'cmake is required' >&2; exit 2; }

if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$(dirname "$SRC")"
  git clone --filter=blob:none https://github.com/duckdb/duckdb-java.git "$SRC"
fi
git -C "$SRC" fetch --depth 1 origin "$COMMIT"
git -C "$SRC" checkout --detach "$COMMIT"

rm -rf "$BUILD"
mkdir -p "$BUILD" "$OUT"
cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS='-static-libstdc++ -static-libgcc' \
  -DCMAKE_SHARED_LINKER_FLAGS='-static-libstdc++ -static-libgcc' \
  -DCMAKE_MODULE_LINKER_FLAGS='-static-libstdc++ -static-libgcc'
cmake --build "$BUILD" --target duckdb_java

arch=$(uname -m)
case "$arch" in
  x86_64) suffix=amd64 ;;
  aarch64) suffix=arm64 ;;
  *) printf 'unsupported Linux architecture: %s\n' "$arch" >&2; exit 2 ;;
esac
lib=$(find "$BUILD" -type f -name 'libduckdb_java.so_*' -print -quit)
[ -n "$lib" ] || { printf '%s\n' 'DuckDB JNI library was not produced' >&2; exit 1; }
needed=$(readelf -d "$lib" | sed -n 's/.*\[\([^]]*\)\].*/\1/p' | sort -u)
if printf '%s\n' "$needed" | rg -q '^(libstdc\\+\\+|libgcc_s)\.so'; then
  printf '%s\n' 'DuckDB JNI still has a dynamic C++ runtime dependency' >&2
  exit 1
fi
mkdir -p "$OUT"
cp "$lib" "$OUT/libduckdb_java.so_linux_$suffix"
printf 'built %s -> %s\n' "$lib" "$OUT/libduckdb_java.so_linux_$suffix"
