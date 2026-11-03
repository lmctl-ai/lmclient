#!/usr/bin/env python3
"""The committed lmclient version floor plus workflow run number is stable."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
current = (root / "VERSION").read_text(encoding="utf-8").strip()
match = re.fullmatch(r"(0\.2)\.(\d+)", current)
assert match, current
patch = int(match[2])

def derive(*args):
    return subprocess.check_output(["bash", root / "scripts/derive-release-version.sh", *args], text=True).strip()

assert derive("--diagnostic") == current
assert derive("1") == f"0.2.{patch + 1}"
assert derive("11") == f"0.2.{patch + 11}"
assert derive("11") == f"0.2.{patch + 11}"

with tempfile.TemporaryDirectory(prefix="lmclient-version-stamp-") as temp:
    work = Path(temp)
    (work / "scripts").mkdir()
    (work / "src/main/java/ai/lmctl/lmclient").mkdir(parents=True)
    for name in ("VERSION", "pom.xml", "THIRD_PARTY_NOTICES"):
        shutil.copyfile(root / name, work / name)
    shutil.copyfile(root / "src/main/java/ai/lmctl/lmclient/Main.java", work / "src/main/java/ai/lmctl/lmclient/Main.java")
    shutil.copyfile(root / "scripts/stamp-version.sh", work / "scripts/stamp-version.sh")
    stamped = f"0.2.{patch + 11}"
    subprocess.run(["bash", work / "scripts/stamp-version.sh", stamped], check=True)
    assert (work / "VERSION").read_text().strip() == stamped
    assert re.search(rf'<artifactId>lmclient</artifactId>\s*<version>{re.escape(stamped)}</version>', (work / "pom.xml").read_text())
    assert f'VERSION = "{stamped}"' in (work / "src/main/java/ai/lmctl/lmclient/Main.java").read_text()
    assert (work / "THIRD_PARTY_NOTICES").read_text().startswith(f"lmclient {stamped}")
print("PASS lmclient run-derived version contract")
