#!/usr/bin/env python3
"""Exercise configured server drivers through an isolated lmclient executable.

URLs and credentials are supplied by CI. Child output is intentionally discarded:
database errors can echo connection details and must never become CI log content.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import time

if len(sys.argv) != 2:
    raise SystemExit("usage: test-network.py PATH_TO_LMCLIENT")
binary = str(Path(sys.argv[1]).resolve())
timeout_seconds = 60

def run(driver, url, user, password, *args):
    env = os.environ.copy()
    if user:
        env["LMCLIENT_USER"] = user
    if password:
        env["LMCLIENT_PASSWORD"] = password
    env.pop("LMCLIENT_URL", None)
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
    table = "lmclient_network_" + uuid.uuid4().hex[:16]
    quoted = '"' + table + '"' if driver == "postgres" else "[" + table + "]"
    try:
        ready = False
        for _ in range(20):
            try:
                run(driver, url, user, password, "--sql", "SELECT 1")
                ready = True
                break
            except RuntimeError:
                time.sleep(3)
        if not ready:
            raise RuntimeError(f"{driver} server did not become ready")
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
        if driver == "postgres":
            typed = json.loads(run(driver,url,user,password,"--sql",
                "SELECT '{\"ok\":true}'::jsonb AS payload, '00000000-0000-0000-0000-000000000001'::uuid AS id", "--format","json"))
            if json.loads(typed[0]["payload"]) != {"ok":True} or typed[0]["id"] != "00000000-0000-0000-0000-000000000001":
                raise RuntimeError("postgres typed value mismatch")
        else:
            typed = json.loads(run(driver,url,user,password,"--sql","SELECT CAST(N'<root>ok</root>' AS XML) AS payload","--format","json"))
            if "<root>ok</root>" not in typed[0]["payload"]:
                raise RuntimeError("sqlserver XML value mismatch")
    finally:
        try:
            run(driver, url, user, password, "--sql", f"DROP TABLE {quoted}")
        except RuntimeError:
            pass

configured = 0
for driver, prefix in (("postgres", "LMCLIENT_POSTGRES"), ("sqlserver", "LMCLIENT_MSSQL")):
    url = os.environ.get(prefix + "_URL")
    if not url:
        print(f"{driver}: SKIP (URL not configured)")
        continue
    configured += 1
    exercise(driver, url, os.environ.get(prefix + "_USER") or os.environ.get("LMCLIENT_USER"),
             os.environ.get(prefix + "_PASSWORD") or os.environ.get("LMCLIENT_PASSWORD"))
    print(f"{driver}: PASS")
if not configured:
    print("network checks: SKIP (no server URLs configured)")
