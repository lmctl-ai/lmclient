#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/third_party/duckdb-java"
BUILD="$ROOT/target/duckdb-java-build"
STATIC_OUT="$ROOT/target/static-jni"
COMMIT=a561d2ddadde231402411ce76112779bc34b57f0
fingerprint="$COMMIT:$(sha256sum "$ROOT/scripts/build-duckdb.sh" | cut -d ' ' -f 1)"
if [ -s "$STATIC_OUT/libduckdb_java.a" ] && [ -f "$STATIC_OUT/duckdb.pin" ] && [ "$(cat "$STATIC_OUT/duckdb.pin")" = "$fingerprint" ]; then
  printf '%s\n' 'verified cached DuckDB static JNI archive'
  exit 0
fi

[ "$(uname -s)" = Linux ] || { printf '%s\n' 'custom DuckDB JNI build currently supports Linux runners only' >&2; exit 2; }
command -v git >/dev/null 2>&1 || { printf '%s\n' 'git is required' >&2; exit 2; }
command -v cmake >/dev/null 2>&1 || { printf '%s\n' 'cmake is required' >&2; exit 2; }

if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$(dirname "$SRC")"
  git clone --filter=blob:none https://github.com/duckdb/duckdb-java.git "$SRC"
fi
git -C "$SRC" fetch --depth 1 origin "$COMMIT"
git -C "$SRC" checkout --detach "$COMMIT"

mkdir -p "$BUILD"
cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS='-static-libstdc++ -static-libgcc' \
  -DCMAKE_SHARED_LINKER_FLAGS='-Wl,--as-needed -static-libstdc++ -static-libgcc -Wl,-Bstatic -lstdc++ -lgcc -lgcc_eh -Wl,-Bdynamic' \
  -DCMAKE_MODULE_LINKER_FLAGS='-Wl,--as-needed -static-libstdc++ -static-libgcc -Wl,-Bstatic -lstdc++ -lgcc -lgcc_eh -Wl,-Bdynamic' \
  -DCMAKE_CXX_STANDARD_LIBRARIES='-ldl -Wl,-Bstatic -lstdc++ -lgcc -lgcc_eh -Wl,-Bdynamic'
cmake --build "$BUILD" --target duckdb_java --parallel "${LMCLIENT_DUCKDB_JOBS:-2}"

arch=$(uname -m)
case "$arch" in
  x86_64) suffix=amd64 ;;
  aarch64) suffix=arm64 ;;
  *) printf 'unsupported Linux architecture: %s\n' "$arch" >&2; exit 2 ;;
esac
lib=$(find "$BUILD" -type f -name 'libduckdb_java.so_*' -print -quit)
[ -n "$lib" ] || { printf '%s\n' 'DuckDB JNI library was not produced' >&2; exit 1; }

# Native-image links the JNI implementation into the executable. Keep the
# shared object only as a diagnostic reference; it is never packaged because
# its loader-visible C++ runtime dependencies violate Rule 14.
mkdir -p "$STATIC_OUT"
jni_object=$(find "$BUILD/CMakeFiles/duckdb_java.dir" -type f -name 'duckdb_java.cpp.o' -print -quit)
[ -n "$jni_object" ] || { printf '%s\n' 'DuckDB JNI entry object was not produced' >&2; exit 1; }
renamed="$STATIC_OUT/duckdb_java_entry.o"
cp "$jni_object" "$renamed"
objcopy --redefine-sym JNI_OnLoad=lmclient_duckdb_legacy_onload --redefine-sym JNI_OnUnload=JNI_OnUnload_duckdb_java "$renamed"
cat > "$STATIC_OUT/duckdb_onload.c" <<'C'
#include <jni.h>
extern jint lmclient_duckdb_legacy_onload(JavaVM *, void *);
JNIEXPORT jint JNICALL JNI_OnLoad_duckdb_java(JavaVM *vm, void *reserved) {
    jint version = lmclient_duckdb_legacy_onload(vm, reserved);
    /* The JNI specification requires 1.8 or newer for statically linked libraries. */
    return version >= JNI_VERSION_1_1 ? JNI_VERSION_1_8 : version;
}
C
cc -fPIC -O2 -I"$JAVA_HOME/include" -I"$JAVA_HOME/include/linux" -c "$STATIC_OUT/duckdb_onload.c" -o "$STATIC_OUT/duckdb_onload.o"
archive="$STATIC_OUT/libduckdb_java.a"
python3 - "$BUILD" "$lib" "$archive" "$renamed" <<'PY'
from pathlib import Path
import subprocess,sys
build,library,archive,entry = map(Path,sys.argv[1:])
query = subprocess.run(['ninja','-C',str(build),'-t','query',library.name],check=True,capture_output=True,text=True,timeout=30)
objects = [build / line.strip() for line in query.stdout.splitlines()
           if line.strip().endswith('.o') and 'duckdb_java.cpp.o' not in line]
assert objects and all(path.is_file() for path in objects), 'current DuckDB object list is incomplete'
archive.unlink(missing_ok=True)
shim = archive.parent / 'duckdb_onload.o'
subprocess.run(['ar','rcs',str(archive),*[str(path) for path in objects],str(entry),str(shim)],check=True,timeout=120)
print(f'built {archive}: {len(objects)+2} objects from the current Ninja target and static JNI shim')
PY
printf '%s\n' "$fingerprint" > "$STATIC_OUT/duckdb.pin"
