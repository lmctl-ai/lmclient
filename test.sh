#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v timeout >/dev/null 2>&1; then deadline=timeout
elif command -v gtimeout >/dev/null 2>&1; then deadline=gtimeout
else echo 'GNU timeout/coreutils is required' >&2; exit 2; fi
"$deadline" 300 mvn -B -q verify
python3 tests/check-host-flags.py sha256:bc50acc669dde4a0818adfc40592c5917dcb9284564d186cf1a1dcc49390be3c java -jar "target/lmclient-$(cat VERSION)-all.jar"
"$deadline" 30 python3 scripts/check-version.py
"$deadline" 30 python3 scripts/test-native-resources.py
"$deadline" 30 python3 scripts/test-lmmock-harness.py
"$deadline" 300 python3 scripts/test-cli.py
for area in redis mail queue mqtt mongo cred http oauth llm github kafka network; do
  "$deadline" 600 python3 "scripts/test-$area.py" "target/lmclient-$(cat VERSION)-all.jar"
done
if [[ -n "${LMCLIENT_NATIVE_BINARY:-}" ]]; then
  "$deadline" 300 python3 scripts/test-cli.py "$LMCLIENT_NATIVE_BINARY"
  if [[ "$(uname -s)" == Linux ]]; then
    "$deadline" 30 python3 scripts/check-linux-linkage.py "$LMCLIENT_NATIVE_BINARY"
  fi
fi

# Gallery files are generated siblings in some checkouts. Validate every file that
# is present; a missing tracked artifact is an error, while an absent untracked
# sibling is an explicit rerender skip.
python3 - <<'PY'
from pathlib import Path
import re
import subprocess
root = Path.cwd()
readme = (root / "README.md").read_text(encoding="utf-8")
paths = re.findall(r'(?:src|href)=["\']([^"\']+\.png)["\']|\]\(([^)]+\.png)\)', readme, flags=re.I)
paths = [a or b for a, b in paths]
paths.extend(str(path.relative_to(root)) for path in (root / "docs/images").glob("*.png"))
paths = sorted(set(paths))
for raw in paths:
    path = root / raw.lstrip("./")
    if not path.is_file():
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", raw.lstrip("./")], cwd=root, capture_output=True).returncode == 0
        if tracked:
            raise SystemExit(f"gallery image missing from checkout: {raw}")
        print(f"gallery image SKIP (missing untracked sibling artifact; rerender required): {raw}")
        continue
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"gallery image is not a PNG: {raw}")
    if len(data) > 300_000:
        raise SystemExit(f"gallery image exceeds 300 KB: {raw}")
    print(f"gallery image OK: {raw}")
for raw in sorted(set(re.findall(r'(?:raw[^ ]*/)?examples/([A-Za-z0-9_.-]+\.lms)', readme))):
    example = root / "examples" / raw
    if not example.is_file():
        raise SystemExit(f"README example missing: examples/{raw}")
PY

if [[ -n "${LMCLIENT_LMSCRIPT:-}" ]]; then
  "$deadline" 900 python3 - "$LMCLIENT_LMSCRIPT" <<'PY'
from pathlib import Path
import subprocess, sys
compiler = sys.argv[1]
examples = sorted(Path("examples").glob("*.lms"))
if not examples:
    raise SystemExit("no DSL examples found")
for example in examples:
    subprocess.run([compiler, str(example)], check=True, timeout=120)
print(f"DSL examples OK: {len(examples)}")
PY
else
  echo "DSL examples SKIP (set LMCLIENT_LMSCRIPT when sibling compiler and build launcher are available)"
fi
