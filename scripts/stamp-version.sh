#!/usr/bin/env bash
# Stamp the temporary CI checkout before Maven and native-image packaging.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
version=${1:-}
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'expected MAJOR.MINOR.PATCH' >&2; exit 2; }
python3 - "$version" <<'PY'
from pathlib import Path
import re
import sys

version = sys.argv[1]
root = Path.cwd()
(root / 'VERSION').write_text(version + '\n', encoding='utf-8')

pom_path = root / 'pom.xml'
pom = pom_path.read_text(encoding='utf-8')
pom, pom_count = re.subn(
    r'(<artifactId>lmclient</artifactId>\s*<version>)[^<]+(</version>)',
    rf'\g<1>{version}\g<2>', pom, count=1)
main_path = root / 'src/main/java/ai/lmctl/lmclient/Main.java'
main = main_path.read_text(encoding='utf-8')
main, main_count = re.subn(
    r'(public static final String VERSION = ")[^"]+(";\s*)',
    rf'\g<1>{version}\g<2>', main, count=1)
notices_path = root / 'THIRD_PARTY_NOTICES'
notices = notices_path.read_text(encoding='utf-8')
notices, notices_count = re.subn(
    r'(\Almclient )[0-9]+\.[0-9]+\.[0-9]+',
    rf'\g<1>{version}', notices, count=1)
if (pom_count, main_count, notices_count) != (1, 1, 1):
    raise SystemExit('lmclient version marker changed; refusing an ambiguous stamp')
pom_path.write_text(pom, encoding='utf-8')
main_path.write_text(main, encoding='utf-8')
notices_path.write_text(notices, encoding='utf-8')
PY
