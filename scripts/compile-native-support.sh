#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/native_resources.py --write-args target/native-resources.args
: "${JAVA_HOME:?GraalVM JAVA_HOME is required}"
mkdir -p target/classes
separator=:
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) separator=';' ;; esac
"$JAVA_HOME/bin/javac" --add-modules org.graalvm.nativeimage,org.graalvm.word \
  -cp "$JAVA_HOME/lib/svm/builder/svm.jar${separator}target/classes" \
  -d target/classes src/native/java/ai/lmctl/lmdb/*.java
