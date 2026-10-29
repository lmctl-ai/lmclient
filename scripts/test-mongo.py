#!/usr/bin/env python3
"""Behavioral checks for the mongo area against the shaded jar or a native binary.

Usage: python3 scripts/test-mongo.py [path-to-lmclient-binary]
Usage and envelope checks always run. Live checks start a throwaway mongo:7
container on an ephemeral loopback port and always remove it; they are skipped
with a clear message when docker is unavailable. LMCLIENT_MONGO_URL, when set,
is used instead of a container (CI service container).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
COMMAND = ([str(Path(sys.argv[1]).resolve())] if len(sys.argv) > 1 else
           ["java", "-jar", str(ROOT / f"target/lmclient-{VERSION}-all.jar")])
checks = 0

def run(*args, code=0, env=None):
    global checks
    process = subprocess.run(COMMAND + ["mongo", *args], text=True, encoding="utf-8",
                             capture_output=True, timeout=90, env=env)
    assert process.returncode == code, (args[:1], process.returncode, process.stdout, process.stderr)
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, ("exactly one JSON line on stdout", process.stdout)
    envelope = json.loads(lines[0])
    assert envelope.get("ok") is (code == 0), envelope
    if code != 0:
        assert isinstance(envelope["error"].get("code"), str) and envelope["error"].get("message"), envelope
    checks += 1
    return envelope, process

def error(*args, code, expect, env=None):
    envelope, process = run(*args, code=code, env=env)
    assert envelope["error"]["code"] == expect, (expect, envelope)
    return envelope, process

# --- usage and input validation (no server needed) ---
error(code=2, expect="USAGE")
error("fly", code=2, expect="USAGE")
error("ping", code=2, expect="USAGE")                                    # no URL
error("ping", "--url", "http://x", code=2, expect="USAGE")
error("ping", "--url", "mongodb://127.0.0.1:1", "--bogus", "1", code=2, expect="USAGE")
error("ping", "--url", "mongodb://127.0.0.1:1", "--timeout", code=2, expect="USAGE")
error("ping", "--url", "mongodb://127.0.0.1:1", "--db", "x", code=2, expect="USAGE")
error("find", "--url", "mongodb://127.0.0.1:1", "--db", "d", code=2, expect="USAGE")
error("find", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", "--limit", "0", code=2, expect="USAGE")
error("insert", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", code=2, expect="USAGE")
error("insert", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", "--doc", "{bad", code=2, expect="BAD_JSON")
error("insert", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", "--doc", "[1]", code=2, expect="BAD_JSON")
error("find", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", "--filter", "nope", code=2, expect="BAD_JSON")
error("delete", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", code=2, expect="USAGE")   # filter required

# --- unreachable server: CONN, bounded by --timeout, no secret leaks ---
secret = "DO_NOT_LOG_lmclient_mongo_secret"
started = time.monotonic()
_, process = error("ping", "--url", "mongodb://127.0.0.1:1", "--timeout", "1500", code=3, expect="CONN",
                   env={**os.environ, "LMCLIENT_PASSWORD": secret, "LMCLIENT_USER": "tester"})
assert time.monotonic() - started < 30, "timeout was not honoured"
assert secret not in process.stdout + process.stderr
_, process = error("ping", "--url", f"mongodb://tester:{secret}@127.0.0.1:1", "--timeout", "1500", code=3, expect="CONN")
assert secret not in process.stdout + process.stderr

# --- live checks ---
def live(url):
    global checks
    db, coll = "lmclient_test", "items_" + uuid.uuid4().hex[:8]
    base = ["--url", url, "--db", db, "--collection", coll]
    env = {k: v for k, v in os.environ.items() if k != "LMCLIENT_MONGO_URL"}
    envelope, process = run("ping", "--url", url, env=env)
    assert envelope["result"] == {"pong": True}, envelope
    assert process.stderr.strip() == "", ("stderr must stay silent", process.stderr)
    envelope, _ = run("insert", *base, "--doc", '{"name":"tea","qty":3,"tags":["hot","green"]}', env=env)
    oid = envelope["result"]["insertedId"]
    assert isinstance(oid, str) and len(oid) == 24, envelope
    envelope, _ = run("insert", *base, "--doc", '{"_id":"custom-1","name":"coffee","qty":7}', env=env)
    assert envelope["result"] == {"insertedId": "custom-1"}, envelope
    envelope, _ = run("find", *base, env=env)
    docs = envelope["result"]["docs"]
    assert envelope["result"]["count"] == 2 and {d["_id"] for d in docs} == {oid, "custom-1"}, envelope
    assert all(isinstance(d["_id"], str) for d in docs), "_id must be stringified"
    assert next(d for d in docs if d["_id"] == oid)["tags"] == ["hot", "green"]
    envelope, _ = run("find", *base, "--filter", '{"qty":{"$gt":5}}', "--limit", "1", env=env)
    assert envelope["result"]["count"] == 1 and envelope["result"]["docs"][0]["name"] == "coffee", envelope
    envelope, _ = run("find", *base, "--filter", '{"name":"nobody"}', env=env)
    assert envelope["result"] == {"count": 0, "docs": []}, envelope
    envelope, _ = run("find", "--db", db, "--collection", coll, env={**env, "LMCLIENT_MONGO_URL": url})
    assert envelope["result"]["count"] == 2, "LMCLIENT_MONGO_URL fallback"
    envelope, _ = error("find", *base, "--filter", '{"$bogus":1}', code=3, expect="SERVER")
    envelope, _ = run("delete", *base, "--filter", '{"name":"tea"}', env=env)
    assert envelope["result"] == {"deleted": 1}, envelope
    envelope, _ = run("delete", *base, "--filter", "{}", env=env)
    assert envelope["result"] == {"deleted": 1}, envelope
    envelope, _ = run("find", *base, env=env)
    assert envelope["result"]["count"] == 0

def wait_ready(url, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        process = subprocess.run(COMMAND + ["mongo", "ping", "--url", url, "--timeout", "3000"],
                                 text=True, capture_output=True, timeout=60)
        if process.returncode == 0:
            return
        time.sleep(1)
    raise SystemExit(f"mongo at {url} did not become ready: {process.stdout} {process.stderr}")

preset = os.environ.get("LMCLIENT_MONGO_URL")
if preset:
    wait_ready(preset)
    live(preset)
    mode = "live via LMCLIENT_MONGO_URL"
elif shutil.which("docker") and subprocess.run(["docker", "info"], capture_output=True, timeout=60).returncode == 0:
    name = "lmclient-mongo-test-" + uuid.uuid4().hex[:8]
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::27017", "mongo:7"],
                   check=True, capture_output=True, timeout=600)
    try:
        port = subprocess.run(["docker", "port", name, "27017/tcp"], check=True, capture_output=True,
                              text=True, timeout=30).stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        url = f"mongodb://127.0.0.1:{port}"
        wait_ready(url)
        live(url)
        mode = "live via docker"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=120)
else:
    mode = "live checks SKIPPED (docker unavailable and LMCLIENT_MONGO_URL unset)"
print(f"lmclient mongo checks: {checks} passed ({'native' if len(sys.argv) > 1 else 'JVM'}; {mode})")
