#!/usr/bin/env python3
"""Run the same behavioral checks against the JVM launcher and each native binary."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
COMMAND = ([str(Path(sys.argv[1]).resolve())] if len(sys.argv) > 1 else
           ["java", "-jar", str(ROOT / f"target/lmdb-{VERSION}-all.jar")])
checks = 0

def run(*args, code=0, env=None):
    global checks
    process = subprocess.run(COMMAND + list(args), text=True, encoding="utf-8",
                             capture_output=True, timeout=90, env=env)
    assert process.returncode == code, (args[:1], process.returncode, process.stdout, process.stderr)
    checks += 1
    return process

assert run("--version").stdout.strip() == "lmdb " + (ROOT / "VERSION").read_text().strip()
schema = json.loads(run("--dsl-schema").stdout)
assert schema.get("name") == "lmdb" and schema.get("dsl.schema") == 2, schema
assert schema.get("types") and schema.get("functions"), "host schema is incomplete"
assert "PostgreSQL" in run("--notices").stdout
assert "LMDB_MAX_MEMORY_MB" in run("--help").stdout
driver_test = run("--driver-test").stdout
assert driver_test.count(": ok") == 5, driver_test
run("--unknown", code=2)
run("--url", code=2)
run("--url", "jdbc:h2:mem:bad", "--format", "xml", code=2)
run("--url", "jdbc:h2:mem:bad", "--max-rows", "-1", code=2)
run("--url", "jdbc:h2:mem:bad", "--sql", "SELECT 1", "--metadata", "tables", code=2)
run("--url", "jdbc:h2:mem:limit", "--sql", "SELECT X FROM SYSTEM_RANGE(1,3)", "--max-rows", "2", code=3)
assert len(json.loads(run("--url", "jdbc:h2:mem:limit", "--sql", "SELECT X FROM SYSTEM_RANGE(1,10001)", "--max-rows", "10001", "--format", "json").stdout)) == 10001
for invalid in ("0", "-1", "1.5", "lots", "99999999999999999999999"):
    run("--version", code=2, env={**os.environ, "LMDB_MAX_MEMORY_MB": invalid})
for driver, url in (("h2", "jdbc:h2:mem:test"), ("sqlite", "jdbc:sqlite::memory:"), ("duckdb", "jdbc:duckdb:")):
    sql = "CREATE TABLE sales(id INTEGER PRIMARY KEY, item VARCHAR(40), amount DECIMAL(10,2)); INSERT INTO sales VALUES(1,'tea,green',12.50),(2,'coffee',7.25); SELECT item,amount FROM sales ORDER BY id"
    result = run("--url", url, "--sql", sql, "--format", "json")
    rows = json.loads(result.stdout)
    assert len(rows) == 2 and str(list(rows[0].values())[0]) == "tea,green", (driver, rows)
    assert abs(float(list(rows[1].values())[1]) - 7.25) < 1e-10
    result = run("--url", url, "--sql", sql, "--format", "csv")
    assert list(csv.reader(io.StringIO(result.stdout)))[1][0] == "tea,green"
    unicode_sql = "SELECT 'héllo,世界' AS greeting"
    if os.name == "nt" and len(sys.argv) == 1:
        # The upstream JVM's Windows launcher converts argv through the ANSI
        # code page; the native distribution embeds its own UTF-8 manifest.
        with tempfile.TemporaryDirectory(prefix="lmdb-utf8-") as directory:
            sql_file = Path(directory) / "unicode.sql"
            sql_file.write_text(unicode_sql, encoding="utf-8")
            result = run("--url", url, "--file", str(sql_file), "--format", "json")
    else:
        result = run("--url", url, "--sql", unicode_sql, "--format", "json")
    assert "héllo,世界" in result.stdout, (driver, repr(result.stdout))
    run("--url", url, "--sql", "SELECT * FROM missing_table", code=3)
    run("--url", url, "--metadata", "tables", "--format", "json")
    run("--url", url, "--explain", "SELECT 1")
    with tempfile.TemporaryDirectory(prefix="lmdb-test-") as directory:
        sql_file = Path(directory) / "input.sql"
        output = Path(directory) / "result.csv"
        sql_file.write_text(sql, encoding="utf-8")
        run("--url", url, "--file", str(sql_file), "--format", "csv", "--output", str(output))
        assert "tea,green" in output.read_text(encoding="utf-8")
secret = "DO_NOT_LOG_lmdb_test_secret"
failure = run("--url", "jdbc:h2:mem:x;PASSWORD=" + secret, "--sql", "SELECT 1", code=2)
assert secret not in failure.stdout + failure.stderr
failure = run("--url", "jdbc:missing:private-host", "--sql", "SELECT 1", code=3,
              env={**os.environ, "LMDB_PASSWORD": secret})
assert secret not in failure.stdout + failure.stderr

# CI can provide real server URLs and credentials. Keep these opt-in so local
# runs remain stateless, but fail if a configured server cannot execute a query.
for name in ("LMDB_POSTGRES_URL", "LMDB_MSSQL_URL"):
    url = os.environ.get(name)
    if not url:
        print(f"{name} SKIP (server URL not configured)")
        continue
    result = run("--url", url, "--sql", "SELECT 1", "--format", "json")
    assert "1" in result.stdout, (name, result.stdout)
print(f"lmdb CLI checks: {checks} passed ({'native' if len(sys.argv) > 1 else 'JVM'})")
