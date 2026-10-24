#!/usr/bin/env python3
"""Execute self-contained examples with a selected host, and validate their pictures."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
compiler = os.environ.get("LMDB_LMSCRIPT") or shutil.which("lmscript")
if not compiler:
    raise SystemExit("lmscript compiler required; install @lmctl-ai/lmctl@0.2.369")
compiler = str(Path(compiler).resolve())
for example in sorted((root / "examples").glob("*.lms")):
    with tempfile.TemporaryDirectory(prefix="lmdb-example-") as directory:
        subprocess.run([compiler,str(example)],cwd=directory,check=True,timeout=180)
        images = list((Path(directory)/"images").glob("*.png"))
        assert images, "example produced no images: " + example.name
        for image in images:
            data = image.read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) <= 300_000, image.name
            assert int.from_bytes(data[16:20],"big") == 900 and int.from_bytes(data[20:24],"big") == 560, image.name
        print(example.name + ": PASS")
