#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/native_resources.py --write-config target/classes/META-INF/native-image/ai.lmctl/lmclient/native-image.properties
: "${JAVA_HOME:?GraalVM JAVA_HOME is required}"
mkdir -p target/classes
separator=:
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) separator=';' ;; esac
"$JAVA_HOME/bin/javac" --add-modules org.graalvm.nativeimage,org.graalvm.word \
  -cp "$JAVA_HOME/lib/svm/builder/svm.jar${separator}target/classes" \
  -d target/classes src/native/java/ai/lmctl/lmclient/*.java
