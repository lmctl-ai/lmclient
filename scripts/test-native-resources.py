#!/usr/bin/env python3
"""Check every platform's filter against the actual shaded driver resources."""
from pathlib import Path
import re
import zipfile

from native_resources import exclusion_pattern

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text().strip()
with zipfile.ZipFile(root / f"target/lmdb-{version}-all.jar") as jar:
    resources = {entry.filename: entry.file_size for entry in jar.infolist()
                 if entry.file_size and entry.filename.startswith(("libduckdb_java.so_", "org/sqlite/native/"))}

expected = {
    "linux-x64": set(),
    "linux-arm64": set(),
    "macos-arm64": {"libduckdb_java.so_osx_universal", "org/sqlite/native/Mac/aarch64/libsqlitejdbc.dylib"},
    "macos-x64": {"libduckdb_java.so_osx_universal", "org/sqlite/native/Mac/x86_64/libsqlitejdbc.dylib"},
    "windows-x64": {"libduckdb_java.so_windows_amd64", "org/sqlite/native/Windows/x86_64/sqlitejdbc.dll"},
}
for target, names in expected.items():
    pattern = exclusion_pattern(target)
    assert ":" not in pattern, "Graal treats a colon as a module selector"
    kept = {name for name in resources if not re.fullmatch(pattern, name)}
    assert kept == names, (target, kept, names)
    removed = sum(size for name, size in resources.items() if name not in kept)
    print(f"native resource filter: {target}: keep {sum(resources[n] for n in kept):,} bytes; exclude {removed:,} bytes")
