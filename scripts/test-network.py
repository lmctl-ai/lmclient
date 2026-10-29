#!/usr/bin/env python3
"""Exercise configured server drivers through an isolated lmclient executable.

URLs and credentials are supplied by CI. Child output is intentionally discarded:
database errors can echo connection details and must never become CI log content.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import time
from jvm_noise import java_command
from temp_cleanup import temporary_directory

if len(sys.argv) != 2:
    raise SystemExit("usage: test-network.py PATH_TO_LMCLIENT_OR_JAR")
COMMAND = java_command(sys.argv[1])
timeout_seconds = 60

def run(driver, url, user, password, *args):
    env = os.environ.copy()
    if user:
        env["LMCLIENT_USER"] = user
    if password:
        env["LMCLIENT_PASSWORD"] = password
    env.pop("LMCLIENT_URL", None)
    try:
        process = subprocess.run(COMMAND + ["--url", url, *args], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding="utf-8", timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{driver} network command failed") from None
    if process.returncode != 0:
        raise RuntimeError(f"{driver} network command failed")
    return process.stdout

def exercise(driver, url, user, password, execute=run):
    table = "lmclient_network_" + uuid.uuid4().hex[:16]
    quoted = '"' + table + '"' if driver == "postgres" else "[" + table + "]"
    try:
        ready = False
        for _ in range(20):
            try:
                execute(driver, url, user, password, "--sql", "SELECT 1")
                ready = True
                break
            except RuntimeError:
                time.sleep(3)
        if not ready:
            raise RuntimeError(f"{driver} server did not become ready")
        execute(driver, url, user, password, "--sql", f"CREATE TABLE {quoted} (id INTEGER PRIMARY KEY, label VARCHAR(40)); INSERT INTO {quoted} VALUES (1, 'network-ok');")
        csv = execute(driver, url, user, password, "--sql", f"SELECT id,label FROM {quoted}", "--format", "csv")
        if "network-ok" not in csv or "1" not in csv:
            raise RuntimeError(f"{driver} query result mismatch")
        data = json.loads(execute(driver, url, user, password, "--sql", f"SELECT label FROM {quoted}", "--format", "json"))
        if not data or data[0].get("label") != "network-ok":
            raise RuntimeError(f"{driver} JSON result mismatch")
        columns = execute(driver, url, user, password, "--metadata", "columns", "--table", table, "--format", "json")
        if "label" not in columns.lower():
            raise RuntimeError(f"{driver} metadata mismatch")
        execute(driver, url, user, password, "--explain", f"SELECT id FROM {quoted}")
        if driver == "postgres":
            typed = json.loads(execute(driver,url,user,password,"--sql",
                "SELECT '{\"ok\":true}'::jsonb AS payload, '00000000-0000-0000-0000-000000000001'::uuid AS id", "--format","json"))
            if json.loads(typed[0]["payload"]) != {"ok":True} or typed[0]["id"] != "00000000-0000-0000-0000-000000000001":
                raise RuntimeError("postgres typed value mismatch")
        else:
            typed = json.loads(run(driver,url,user,password,"--sql","SELECT CAST(N'<root>ok</root>' AS XML) AS payload","--format","json"))
            if "<root>ok</root>" not in typed[0]["payload"]:
                raise RuntimeError("sqlserver XML value mismatch")
    finally:
        try:
            execute(driver, url, user, password, "--sql", f"DROP TABLE {quoted}")
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

# Additive, cross-platform PostgreSQL wire tier. Keep configured PostgreSQL and
# SQL Server checks above intact; an optional lmmock skip must not bypass them.
# SQL Server and real SQL semantics (constraints, transactions, arbitrary SQL,
# TLS/SCRAM) remain real-server-only. The mock supports this exact id/label shape.
spec = importlib.util.spec_from_file_location('lmmock_helpers', Path(__file__).with_name('lmmock-helpers.py'))
mock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mock)

def mock_run(driver, url, user, password, *args):
    # SQL files preserve quotes (notably JSONB literals) through Windows argv
    # transport. The real-server tier retains its existing command transport.
    if '--sql' not in args:
        return run(driver, url, user, password, *args)
    arguments = list(args)
    index = arguments.index('--sql')
    with temporary_directory(prefix='lmclient-postgres-sql-') as directory:
        path = Path(directory) / 'query.sql'
        path.write_text(arguments[index + 1], encoding='utf-8')
        arguments[index:index + 2] = ['--file', str(path)]
        return run(driver, url, user, password, *arguments)


with mock.lmmock_proto('postgres', {
    'users': {'mock-user': 'dummy-postgres-password'},
    'database': 'fixture',
    'unknownSelectError': True,
}) as base:
    if not base.startswith('postgres://'):
        raise RuntimeError('lmmock returned an invalid PostgreSQL URL')
    url = 'jdbc:postgresql://' + base.removeprefix('postgres://') + '/fixture'
    exercise('postgres', url, 'mock-user', 'dummy-postgres-password', execute=mock_run)
print('postgres lmmock: PASS 7 checks (connect, create/insert, CSV, JSON, columns, EXPLAIN, JSONB/UUID); DROP cleanup attempted')
