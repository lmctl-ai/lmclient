#!/usr/bin/env python3
"""Keep only the JDBC JNI resources that the native target can load."""
import argparse
import json
import platform
from pathlib import Path
import re
import sys


def target_name():
    system = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform)
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    target = f"{system}-{arch}"
    if target not in TARGET_RESOURCES:
        raise SystemExit(f"unsupported native target: {target}")
    return target


TARGET_RESOURCES = {
    # Linux uses statically linked JNI archives, not extracted shared libraries.
    "linux-x64": (),
    "linux-arm64": (),
    "macos-arm64": ("libduckdb_java.so_osx_universal", "org/sqlite/native/Mac/aarch64/libsqlitejdbc.dylib"),
    "macos-x64": ("libduckdb_java.so_osx_universal", "org/sqlite/native/Mac/x86_64/libsqlitejdbc.dylib"),
    "windows-x64": ("libduckdb_java.so_windows_amd64", "org/sqlite/native/Windows/x86_64/sqlitejdbc.dll"),
}


def exclusion_pattern(target):
    # Character classes avoid backslash processing in native-image @argument files.
    patterns = []
    for prefix in ("libduckdb_java.so_", "org/sqlite/native/"):
        keep = [name[len(prefix):] for name in TARGET_RESOURCES[target] if name.startswith(prefix)]
        suffix = "(?!(?:" + "|".join(re.escape(name).replace(r"\.", "[.]") for name in keep) + ")$)" if keep else ""
        patterns.append(re.escape(prefix).replace(r"\.", "[.]") + suffix + ".*")
    return "(?:" + "|".join(patterns) + ")"


def check_inventory(path, target):
    resources = json.loads(path.read_text(encoding="utf-8"))
    actual = {}
    for resource in resources:
        name = resource["name"]
        if not name.startswith(("libduckdb_java.so_", "org/sqlite/native/")):
            continue
        if resource.get("is_directory") or resource.get("is_missing"):
            continue
        actual[name] = sum(entry["size"] for entry in resource["entries"])
    expected = set(TARGET_RESOURCES[target])
    if set(actual) != expected or any(size <= 0 for size in actual.values()):
        raise SystemExit(f"wrong embedded JNI resources for {target}: expected {sorted(expected)}, got {actual}")
    print(f"embedded JNI resources: {target}: {len(actual)} libraries, {sum(actual.values()):,} bytes")
    for name, size in sorted(actual.items()):
        print(f"  {name}: {size:,} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-args", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    target = target_name()
    if args.write_args:
        args.write_args.parent.mkdir(parents=True, exist_ok=True)
        args.write_args.write_text("-H:ExcludeResources=" + exclusion_pattern(target) + "\n", encoding="utf-8")
        print(f"native resource target: {target}")
    if args.check:
        check_inventory(args.check, target)
    if not args.write_args and not args.check:
        parser.error("choose --write-args or --check")


if __name__ == "__main__":
    main()
