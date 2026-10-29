#!/usr/bin/env python3
"""Behavioral checks for the mongo area against the shaded jar or a native binary.

Usage: python3 scripts/test-mongo.py [path-to-lmclient-binary]
When Docker is unavailable, the suite skips cleanly before invoking the client.
Live checks start a throwaway mongo:7 container on an ephemeral loopback port
and always remove it; setup failures also skip with Docker diagnostics. LMCLIENT_MONGO_URL, when set,
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
TARGET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / f"target/lmclient-{VERSION}-all.jar"
COMMAND = ["java", "-jar", str(TARGET)] if TARGET.suffix == ".jar" else [str(TARGET)]  # jar or native binary
NATIVE = TARGET.suffix != ".jar"
checks = 0

# Usage checks must not see a CI-provided LMCLIENT_MONGO_URL; live() passes it explicitly.
BASE_ENV = {k: v for k, v in os.environ.items() if k != "LMCLIENT_MONGO_URL"}

def run(*args, code=0, env=None):
    global checks
    process = subprocess.run(COMMAND + ["mongo", *args], text=True, encoding="utf-8",
                             capture_output=True, timeout=90, env=BASE_ENV if env is None else env)
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


# Infrastructure failures skip live tests; application assertions still fail normally.
class DockerUnavailable(Exception):
    pass


def docker_setup(*args, timeout=600):
    try:
        result = subprocess.run(['docker', *args], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        detail = exc.stderr or ''
        if isinstance(detail, bytes):
            detail = detail.decode('utf-8', errors='replace')
        raise DockerUnavailable(f'Docker setup timed out after {timeout}s: {detail.strip()}') from None
    except OSError as exc:
        raise DockerUnavailable(f'Docker unavailable: {exc.strerror}') from None
    if result.returncode:
        raise DockerUnavailable(f'Docker setup exited {result.returncode}: {result.stderr.strip()}')
    return result.stdout.strip()


def skip_docker(reason):
    message = str(reason)
    for key in ('SECRET', 'WRONG', 'secret'):
        value = globals().get(key)
        if value:
            message = message.replace(value, '(redacted)')
    print('mongo: SKIP live checks (' + message + ')')
    sys.exit(0)


def require_docker():
    if not shutil.which('docker'):
        skip_docker('docker executable absent')
    try:
        os_type = docker_setup('info', '--format', '{{.OSType}}', timeout=30).lower()
        if os_type != 'linux':
            skip_docker(f"{os_type or 'unknown'} Docker daemon cannot run this suite's Linux image")
    except DockerUnavailable as exc:
        skip_docker(exc)


def published_port(name, container_port):
    output = docker_setup('port', name, container_port, timeout=30)
    try:
        port = int(output.splitlines()[0].rsplit(':', 1)[1])
        if not 1 <= port <= 65535:
            raise ValueError()
        return port
    except (IndexError, ValueError):
        raise DockerUnavailable('Docker did not report an ephemeral published port') from None


def remove_container(name):
    # Attempt cleanup even if a pull/start timed out or partially created a container.
    # Do not mask either a skip or a failed live assertion if the daemon disappears.
    try:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        print('mongo: WARNING Docker cleanup unavailable for ' + name)

if not os.environ.get('LMCLIENT_MONGO_URL'):
    require_docker()

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
                   env={**BASE_ENV, "LMCLIENT_PASSWORD": secret, "LMCLIENT_USER": "tester"})
assert time.monotonic() - started < 30, "timeout was not honoured"
assert secret not in process.stdout + process.stderr
_, process = error("ping", "--url", f"mongodb://tester:{secret}@127.0.0.1:1", "--timeout", "1500", code=3, expect="CONN")
assert secret not in process.stdout + process.stderr

# --- live checks ---
def live(url):
    global checks
    db, coll = "lmclient_test", "items_" + uuid.uuid4().hex[:8]
    base = ["--url", url, "--db", db, "--collection", coll]
    env = BASE_ENV
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
else:
    name = "lmclient-mongo-test-" + uuid.uuid4().hex[:8]
    try:
        docker_setup("run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::27017", "mongo:7")
        port = published_port(name, "27017/tcp")
        url = f"mongodb://127.0.0.1:{port}"
        wait_ready(url)
        live(url)
        mode = "live via docker"
    except DockerUnavailable as exc:
        skip_docker(exc)
    finally:
        remove_container(name)
print(f"lmclient mongo checks: {checks} passed ({'native' if NATIVE else 'JVM'}; {mode})")
