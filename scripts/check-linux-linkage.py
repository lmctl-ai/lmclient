#!/usr/bin/env python3
"""Check that a Linux lmdb image only loads the Rule 14 glibc allowlist."""
import subprocess
import sys

allowed = {"libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1"}
if len(sys.argv) != 2:
    raise SystemExit("usage: check-linux-linkage.py PATH")
path = sys.argv[1]
try:
    out = subprocess.check_output(["readelf", "-d", path], text=True, stderr=subprocess.STDOUT, timeout=30)
except (OSError, subprocess.CalledProcessError) as exc:
    raise SystemExit(f"readelf failed: {exc}")
needed = []
for line in out.splitlines():
    if "(NEEDED)" not in line:
        continue
    left = line.find("[")
    right = line.find("]", left + 1)
    if left >= 0 and right > left:
        needed.append(line[left + 1:right])
bad = [name for name in needed if name not in allowed and not name.startswith("ld-linux")]
if bad:
    raise SystemExit("forbidden dynamic dependencies: " + ", ".join(bad))
print("Rule 14 linkage OK: " + (", ".join(needed) if needed else "no NEEDED entries"))
