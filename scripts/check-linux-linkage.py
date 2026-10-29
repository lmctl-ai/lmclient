#!/usr/bin/env python3
"""Check lmclient Linux dynamic dependencies and glibc ABI policy."""
from __future__ import annotations
import os, re, shutil, subprocess, sys
from pathlib import Path

TIMEOUT_SECONDS = 30
MAX_GLIBC = (2, 35, 0)
ALLOWED_NEEDED = {"libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1"}
GLIBC_VERSION_RE = re.compile(r"GLIBC_(\d+)(?:\.(\d+))?(?:\.(\d+))?")
NEEDED_RE = re.compile(r"\(NEEDED\).*?\[([^]]+)\]")

class LinkageError(Exception):
    pass

def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS, env={**os.environ, "LC_ALL": "C"})
    except FileNotFoundError as exc:
        raise LinkageError(f"required command unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LinkageError(f"{command[0]} timed out after {TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise LinkageError(f"could not run {command[0]}: {exc}") from exc

def _check_glibc_versions(text: str) -> None:
    versions = [tuple(int(match.group(i) or 0) for i in range(1, 4))
                for match in GLIBC_VERSION_RE.finditer(text)]
    too_new = sorted(set(version for version in versions if version > MAX_GLIBC))
    if too_new:
        rendered = ", ".join(".".join(str(part) for part in version[:2]) for version in too_new)
        raise LinkageError(f"requires glibc newer than 2.35: GLIBC_{rendered}")

def _check_needed(needed: list[str], source: str) -> None:
    if "libc.so.6" not in needed:
        raise LinkageError(f"{source} executable does not dynamically require libc.so.6 (static or invalid executable)")
    loaders = {name for name in needed if name.startswith("ld-linux") and "/" not in name}
    unexpected = sorted(set(needed) - ALLOWED_NEEDED - loaders)
    if unexpected:
        raise LinkageError(f"disallowed dynamic dependencies: {', '.join(unexpected)}")

def _check_readelf(host: str, readelf: str) -> None:
    dynamic = _run([readelf, "-d", host])
    if dynamic.returncode != 0:
        raise LinkageError(f"readelf could not inspect {host}")
    _check_needed(NEEDED_RE.findall(dynamic.stdout), "dynamic")
    versions = _run([readelf, "--version-info", host])
    if versions.returncode != 0:
        raise LinkageError("readelf could not inspect glibc version requirements")
    _check_glibc_versions(versions.stdout)

def _ldd_dependencies(output: str) -> list[str]:
    dependencies = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("statically linked", "not a dynamic executable", "linux-vdso")):
            continue
        name = line.split("=>", 1)[0].strip() if "=>" in line else line.split(None, 1)[0]
        dependencies.append(Path(name).name)
    return dependencies

def _check_ldd(host: str, ldd: str) -> None:
    result = _run([ldd, host])
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if "statically linked" in output or "not a dynamic executable" in output:
        raise LinkageError(f"{host} is static; dynamically linked glibc is required")
    if result.returncode != 0 or "not found" in output:
        raise LinkageError(f"ldd could not resolve all dependencies of {host}: {output.strip()}")
    _check_needed(_ldd_dependencies(output), "ldd")
    print("note: glibc symbol-version audit requires readelf; ldd verified dependency names only")

def check(host: str) -> None:
    readelf = shutil.which("readelf")
    if readelf:
        _check_readelf(host, readelf)
        return
    ldd = shutil.which("ldd")
    if not ldd:
        raise LinkageError("neither readelf nor ldd is available")
    _check_ldd(host, ldd)

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} HOST", file=sys.stderr)
        return 2
    try:
        check(argv[1])
    except LinkageError as exc:
        print(f"linux linkage check failed: {exc}", file=sys.stderr)
        return 1
    print(f"linux linkage check passed: {argv[1]}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
