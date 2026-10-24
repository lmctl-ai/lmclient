#!/usr/bin/env python3
"""Compile lmdb DSL fixtures and exercise the JVM/native host contract."""
import csv
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path(os.environ.get("LMDB_LMSCRIPT") or shutil.which("lmscript") or "/missing/lmscript").resolve()
LAUNCHER = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LMDB_LMDB_LAUNCHER", str(ROOT / "build/lmdb"))).resolve()
if not COMPILER.is_file() or not LAUNCHER.is_file():
    raise SystemExit("DSL test prerequisites missing: pinned lmscript compiler and lmdb launcher are required")

checks = 0

def invoke(args, cwd, timeout, expected=0, env=None):
    global checks
    try:
        process_env = dict(os.environ if env is None else env)
        process_env["PATH"] = str(LAUNCHER.parent) + os.pathsep + os.environ.get("PATH", "")
        command = args
        if os.environ.get("LMDB_TEST_ADDRESS_SPACE_LIMIT") == "1" and args[0] == str(LAUNCHER):
            command = ["bash","-c",'ulimit -v 6291456; exec "$@"',"lmdb-memory-limit",*args]
        p = subprocess.run(command, cwd=cwd, env=process_env, text=True, encoding="utf-8",
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise AssertionError("bounded DSL subprocess failed or timed out") from None
    if p.returncode != expected:
        raise AssertionError(f"DSL fixture returned status {p.returncode} (expected {expected}): {p.stdout[-2000:]} {p.stderr[-2000:]}")
    checks += 1
    return p

def compile_fixture(directory, body, name):
    source = directory / (name + ".lms")
    bytecode = directory / (name + ".dslb")
    source.write_text(
        'host = _dsl_ cli="lmdb" install="github:lmctl-ai/lmdb@latest";\n'
        + body + f'\nend _dsl_\nsavedsl(host, "{bytecode.name}");\n', encoding="utf-8")
    # The outer compiler writes only the requested bytecode. It must not invoke
    # the generated host program; there is no dsl_cli/system call in fixtures.
    invoke([str(COMPILER), str(source)], directory, 120)
    if not bytecode.is_file() or bytecode.stat().st_size == 0:
        raise AssertionError("compiler did not produce DSL bytecode")
    return bytecode

def report(process):
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError:
        raise AssertionError("DSL host did not emit JSON report") from None
    if not isinstance(value, dict):
        raise AssertionError("DSL host report is not an object")
    return value

with tempfile.TemporaryDirectory(prefix="lmdb-dsl-test-") as raw:
    directory = Path(raw)
    body = '''
let c = connect("jdbc:h2:mem:contract;DB_CLOSE_DELAY=-1");
c.exec("CREATE TABLE parent(id INT PRIMARY KEY, label VARCHAR(20)); CREATE TABLE child(id INT PRIMARY KEY, parent_id INT, label VARCHAR(20), FOREIGN KEY(parent_id) REFERENCES parent(id)); CREATE INDEX child_label_idx ON child(label); CREATE VIEW child_view AS SELECT id,label FROM child; INSERT INTO parent VALUES (1,'one'); INSERT INTO child VALUES (1,1,'one'),(2,1,'two');");
let q = c.query("SELECT id,label FROM child ORDER BY id");
q.csv("result.csv"); q.json("result.json");
if (q.rows() != 2) { c.exec("invalid rows getter"); }
if (q.number(0,0) != 1.0) { c.exec("invalid number getter"); }
if (q.text(0,1) != "one") { c.exec("invalid text getter"); }
let tables = c.tables(); let columns = c.columns("CHILD"); let keys = c.keys("CHILD"); let foreign = c.foreign_keys("CHILD"); let indexes = c.indexes("CHILD");
tables.csv("tables.csv"); columns.csv("columns.csv"); keys.csv("keys.csv"); foreign.csv("foreign.csv"); indexes.csv("indexes.csv");
let c2 = connect("jdbc:h2:mem:contract2"); c2.exec("CREATE TABLE parent(id INT PRIMARY KEY, label VARCHAR(20)); CREATE TABLE child(id INT PRIMARY KEY, parent_id INT, label VARCHAR(20), extra INT, FOREIGN KEY(parent_id) REFERENCES parent(id));"); let delta = c.diff(c2); delta.csv("diff.csv");
c.begin(); c.exec("INSERT INTO child VALUES (3,1,'rolled')"); c.rollback();
let after = c.query("SELECT id,label FROM child ORDER BY id"); after.csv("after.csv");
'''
    bytecode = compile_fixture(directory, body, "contract")
    dry = invoke([str(LAUNCHER), "--dsl", str(bytecode), "--dry-run"], directory, 60)
    dry_report = report(dry)
    if not dry_report.get("ok") or not dry_report.get("result", {}).get("dry_run"):
        raise AssertionError("dry-run report mismatch")
    if list(directory.glob("*.csv")) or list(directory.glob("*.json")):
        raise AssertionError("dry-run created result files")
    run = invoke([str(LAUNCHER), "--dsl", str(bytecode)], directory, 90)
    if not report(run).get("ok"):
        raise AssertionError("contract fixture failed")
    rows = list(csv.reader((directory / "result.csv").open(encoding="utf-8")))
    if len(rows) != 3 or rows[1][1] != "one" or rows[2][1] != "two": raise AssertionError("result getter/query mismatch")
    data = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if len(data) != 2 or {key.lower():value for key,value in data[0].items()}["label"] != "one": raise AssertionError("JSON result mismatch")
    for name in ("tables", "columns", "keys", "foreign", "indexes", "diff"):
        if not (directory / (name + ".csv")).is_file(): raise AssertionError(f"missing metadata output: {name}")
    after = list(csv.reader((directory / "after.csv").open(encoding="utf-8")))
    if len(after) != 3: raise AssertionError("transaction rollback did not remove inserted row")
    if not any("EXTRA" in row[-1].upper() for row in csv.reader((directory / "diff.csv").open(encoding="utf-8"))):
        raise AssertionError("schema diff did not report added column")

    for name, body, fragment in (
        ("closed", 'let c = connect("jdbc:h2:mem:closed"); c.close(); c.query("SELECT 1");', "closed"),
        ("bounds", 'let c = connect("jdbc:h2:mem:bounds"); let q = c.query("SELECT 1"); q.text(4,0);', "index"),
        ("nonnumeric", 'let c = connect("jdbc:h2:mem:numeric"); let q = c.query("SELECT \'x\'"); q.number(0,0);', "numeric"),
    ):
        bad = compile_fixture(directory, body, name)
        result = invoke([str(LAUNCHER), "--dsl", str(bad)], directory, 60, expected=3)
        value = report(result)
        if value.get("ok") or value.get("phase") != "run": raise AssertionError(f"{fragment} error report mismatch")

    corrupt = bytearray(bytecode.read_bytes()); corrupt[0] ^= 1
    corrupt_path = directory / "corrupt.dslb"; corrupt_path.write_bytes(corrupt)
    result = invoke([str(LAUNCHER), "--dsl", str(corrupt_path)], directory, 60, expected=3)
    if report(result).get("phase") != "load": raise AssertionError("corrupt bytecode was not a load error")
    mismatch = bytearray(bytecode.read_bytes()); mismatch[6] ^= 1
    mismatch_path = directory / "mismatch.dslb"; mismatch_path.write_bytes(mismatch)
    result = invoke([str(LAUNCHER), "--dsl", str(mismatch_path)], directory, 60, expected=3)
    if report(result).get("code") != "LOAD_SCHEMA_MISMATCH": raise AssertionError("schema mismatch was not detected")

    runaway = compile_fixture(directory, 'let c = connect("jdbc:h2:mem:runaway"); while (true) { let q = c.query("SELECT REPEAT(\'x\',200000)"); }', "runaway")
    env = {**os.environ, "LMDB_MAX_MEMORY_MB": "64"}
    result = invoke([str(LAUNCHER), "--dsl", str(runaway)], directory, 90, expected=3, env=env)
    value = report(result)
    if value.get("phase") != "run" or "memory" not in value.get("message", "").lower() or "LMDB_MAX_MEMORY_MB" not in result.stderr:
        raise AssertionError("memory budget report mismatch")

    bounded = compile_fixture(directory, 'let c = connect("jdbc:h2:mem:bounded"); let i = 0; while (i < 300) { let q = c.query("SELECT REPEAT(\'x\',10000)"); i = i + 1; }', "bounded")
    invoke([str(LAUNCHER), "--dsl", str(bounded)], directory, 180)
    cycles = compile_fixture(directory, 'let i = 0; while (i < 100) { let c = connect("jdbc:h2:mem:cycles"); c.close(); i = i + 1; }', "cycles")
    invoke([str(LAUNCHER), "--dsl", str(cycles)], directory, 90)
    native_close = compile_fixture(directory, 'let a = connect("jdbc:duckdb:"); let b = connect("jdbc:duckdb:"); a.close(); let c = connect("jdbc:duckdb:"); c.close(); b.close();', "native_close")
    invoke([str(LAUNCHER), "--dsl", str(native_close)], directory, 90)
    native_limit = compile_fixture(directory, 'let a = connect("jdbc:duckdb:"); let b = connect("jdbc:duckdb:"); let c = connect("jdbc:duckdb:");', "native_limit")
    result = invoke([str(LAUNCHER), "--dsl", str(native_limit)], directory, 90, expected=3)
    if "native connection limit" not in report(result).get("message", ""):
        raise AssertionError("native connection limit report mismatch")
    if os.environ.get("LMDB_TEST_DEFAULT_BUDGET") == "1":
        default_env = dict(os.environ)
        default_env.pop("LMDB_MAX_MEMORY_MB", None)
        result = invoke([str(LAUNCHER), "--dsl", str(runaway)], directory, 180, expected=3, env=default_env)
        value = report(result)
        if "memory" not in value.get("message", "").lower() or "LMDB_MAX_MEMORY_MB" not in result.stderr:
            raise AssertionError("default memory budget was not enforced")

print(f"lmdb DSL checks: {checks} passed")
