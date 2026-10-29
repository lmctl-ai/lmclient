#!/usr/bin/env python3
"""Fail closed when release metadata drifts between the public surfaces."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", expected):
    raise SystemExit(f"invalid VERSION: {expected!r}")

def require(pattern, path, label):
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    if not match or match.group(1) != expected:
        raise SystemExit(f"{label} does not agree with VERSION {expected}")

require(r"<version>([^<]+)</version>", ROOT / "pom.xml", "pom.xml")
require(r'VERSION\s*=\s*"([^"]+)"', ROOT / "src/main/java/ai/lmctl/lmclient/Main.java", "Main.VERSION")
notice = (ROOT / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
if not re.search(rf"\blmclient\s+{re.escape(expected)}\b", notice):
    raise SystemExit("THIRD_PARTY_NOTICES does not agree with VERSION")

host_api = ROOT / "src/main/java/ai/lmctl/lmclient/HostApi.java"
if not re.search(r'\\"name\\":\\"lmclient\\"', host_api.read_text(encoding="utf-8")):
    raise SystemExit("HostApi schema does not identify lmclient")

tag = subprocess.run(["git", "describe", "--exact-match", "--tags", "HEAD"], cwd=ROOT,
                    capture_output=True, text=True, timeout=20)
if tag.returncode == 0 and tag.stdout.strip() != "v" + expected:
    raise SystemExit(f"tag {tag.stdout.strip()} does not agree with VERSION {expected}")
print(f"version metadata OK: lmclient {expected}")
