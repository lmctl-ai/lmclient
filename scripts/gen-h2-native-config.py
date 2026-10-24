#!/usr/bin/env python3
"""Retain H2's native registrations except the GUI tools unused by this CLI."""
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
jar = Path.home()/".m2/repository/com/h2database/h2/2.3.232/h2-2.3.232.jar"
with zipfile.ZipFile(jar) as archive:
    entries = json.loads(archive.read("META-INF/native-image/reflect-config.json"))
kept = [entry for entry in entries if not entry["name"].startswith(("java.awt.","javax.swing.")) and entry["name"] != "org.h2.tools.GUIConsole"]
assert len(entries) == 30 and len(kept) == 26, "review updated H2 native registrations"
target = root/"src/main/resources/META-INF/native-image/ai.lmctl/lmdb-h2/reflect-config.json"
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(kept,indent=2)+"\n",encoding="utf-8")
print("H2 native registrations: 26 JDBC/storage entries; 4 GUI entries excluded")
