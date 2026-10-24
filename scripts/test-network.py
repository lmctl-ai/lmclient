#!/usr/bin/env python3
"""Exercise configured server drivers through an isolated lmdb executable.

URLs and credentials are supplied by CI. Child output is intentionally discarded:
database errors can echo connection details and must never become CI log content.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

if len(sys.argv) != 2:
    raise SystemExit("usage: test-network.py PATH_TO_LMDB")
binary = str(Path(sys.argv[1]).resolve())
timeout_seconds = 60

def run(driver, url, user, password, *args):
    env = os.environ.copy()
    if user:
        env["LMDB_USER"] = user
    if password:
        env["LMDB_PASSWORD"] = password
    env.pop("LMDB_URL", None)
    try:
        process = subprocess.run([binary, "--url", url, *args], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding="utf-8", timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{driver} network command failed") from None
    if process.returncode != 0:
        raise RuntimeError(f"{driver} network command failed")
    return process.stdout

def exercise(driver, url, user, password):
    table = "lmdb_network_" + uuid.uuid4().hex[:16]
    quoted = '"' + table + '"' if driver == "postgres" else "[" + table + "]"
    try:
        run(driver, url, user, password, "--sql", f"CREATE TABLE {quoted} (id INTEGER PRIMARY KEY, label VARCHAR(40)); INSERT INTO {quoted} VALUES (1, 'network-ok');")
        csv = run(driver, url, user, password, "--sql", f"SELECT id,label FROM {quoted}", "--format", "csv")
        if "network-ok" not in csv or "1" not in csv:
            raise RuntimeError(f"{driver} query result mismatch")
        data = json.loads(run(driver, url, user, password, "--sql", f"SELECT label FROM {quoted}", "--format", "json"))
        if not data or data[0].get("label") != "network-ok":
            raise RuntimeError(f"{driver} JSON result mismatch")
        columns = run(driver, url, user, password, "--metadata", "columns", "--table", table, "--format", "json")
        if "label" not in columns.lower():
            raise RuntimeError(f"{driver} metadata mismatch")
        run(driver, url, user, password, "--explain", f"SELECT id FROM {quoted}")
    finally:
        try:
            run(driver, url, user, password, "--sql", f"DROP TABLE {quoted}")
        except RuntimeError:
            pass

configured = 0
for driver, prefix in (("postgres", "LMDB_POSTGRES"), ("sqlserver", "LMDB_MSSQL")):
    url = os.environ.get(prefix + "_URL")
    if not url:
        print(f"{driver}: SKIP (URL not configured)")
        continue
    configured += 1
    exercise(driver, url, os.environ.get(prefix + "_USER") or os.environ.get("LMDB_USER"),
             os.environ.get(prefix + "_PASSWORD") or os.environ.get("LMDB_PASSWORD"))
    print(f"{driver}: PASS")
if not configured:
    print("network checks: SKIP (no server URLs configured)")
