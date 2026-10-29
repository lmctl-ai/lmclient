#!/usr/bin/env python3
"""Behavioral checks for the mongo area against the shaded jar or a native binary.

Usage: python3 scripts/test-mongo.py [path-to-lmclient-binary]
When Docker is unavailable, the suite skips cleanly before invoking the client.
Live checks start a throwaway mongo:7 container on an ephemeral loopback port
and always remove it; setup failures also skip with Docker diagnostics. LMCLIENT_MONGO_URL, when set,
is used instead of a container. The lmmock tier then runs the same live block against the released
lmmock mongodb mock (scripts/lmmock-helpers.py; strict under LMMOCK_REQUIRED=1 in CI, SKIP locally
when the binary is unobtainable). Only the SCRAM authentication check stays docker-only: the mock
documents that it is auth-less and rejects user configs by design.
is used instead of a container (CI service container).
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from jvm_noise import java_command, strip_jvm_noise
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
TARGET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / f"target/lmclient-{VERSION}-all.jar"
COMMAND = java_command(TARGET)  # jar (with --enable-native-access) or native binary
NATIVE = TARGET.suffix != ".jar"
checks = 0

# Windows: Python's list2cmdline and the Java launcher's own command-line re-parsing disagree on
# embedded double quotes, so JSON documents reach the JVM with their quotes stripped there. The
# area accepts --doc-file / --filter-file; on Windows every quoted JSON argument travels that way,
# on POSIX it stays inline for full argv fidelity. The file flags are also exercised on every OS.
JSON_FILES = tempfile.TemporaryDirectory(prefix="lmclient-mongo-json-")
json_counter = 0

def json_arg(flag, text, via_file=os.name == "nt"):
    global json_counter
    if not via_file:
        return [flag, text]
    json_counter += 1
    path = Path(JSON_FILES.name) / f"{json_counter}.json"
    path.write_text(text, encoding="utf-8")
    return [flag + "-file", str(path)]

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
    message = str(reason).strip() or 'Docker unavailable'
    if len(message) > 300:
        message = message[:300] + '...'
    print('mongo: SKIP docker tier (' + message + ')')
    return 'docker tier SKIPPED'


def require_docker():
    if not shutil.which('docker'):
        raise DockerUnavailable('docker executable absent')
    try:
        os_type = docker_setup('info', '--format', '{{.OSType}}', timeout=30).lower()
        if os_type != 'linux':
            raise DockerUnavailable(f"{os_type or 'unknown'} Docker daemon cannot run this suite's Linux image")
    except DockerUnavailable as exc:
        raise DockerUnavailable(str(exc))


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
error("insert", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", "--doc", "{}", "--doc-file", "x", code=2, expect="USAGE")
error("insert", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", "--doc-file", str(Path(JSON_FILES.name) / "absent.json"), code=2, expect="USAGE")
error("find", "--url", "mongodb://127.0.0.1:1", "--db", "d", "--collection", "c", *json_arg("--filter", "not json", via_file=True), code=2, expect="BAD_JSON")

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
def live(url, scram=False):
    """Live checks shared by the docker and lmmock tiers; scram=True adds the docker-only auth check."""
    global checks
    db, coll = "lmclient_test", "items_" + uuid.uuid4().hex[:8]
    base = ["--url", url, "--db", db, "--collection", coll]
    env = BASE_ENV
    envelope, process = run("ping", "--url", url, env=env)
    assert envelope["result"] == {"pong": True}, envelope
    assert strip_jvm_noise(process.stderr).strip() == "", ("stderr must stay silent", process.stderr)
    envelope, _ = run("insert", *base, *json_arg("--doc", '{"name":"tea","qty":3,"tags":["hot","green"]}'), env=env)
    oid = envelope["result"]["insertedId"]
    assert isinstance(oid, str) and len(oid) == 24, envelope
    envelope, _ = run("insert", *base, *json_arg("--doc", '{"_id":"custom-1","name":"coffee","qty":7}', via_file=True), env=env)
    assert envelope["result"] == {"insertedId": "custom-1"}, envelope
    envelope, _ = run("find", *base, env=env)
    docs = envelope["result"]["docs"]
    assert envelope["result"]["count"] == 2 and {d["_id"] for d in docs} == {oid, "custom-1"}, envelope
    assert all(isinstance(d["_id"], str) for d in docs), "_id must be stringified"
    assert next(d for d in docs if d["_id"] == oid)["tags"] == ["hot", "green"]
    envelope, _ = run("find", *base, *json_arg("--filter", '{"qty":{"$gt":5}}'), "--limit", "1", env=env)
    assert envelope["result"]["count"] == 1 and envelope["result"]["docs"][0]["name"] == "coffee", envelope
    envelope, _ = run("find", *base, *json_arg("--filter", '{"name":"nobody"}', via_file=True), env=env)
    assert envelope["result"] == {"count": 0, "docs": []}, envelope
    envelope, _ = run("find", "--db", db, "--collection", coll, env={**env, "LMCLIENT_MONGO_URL": url})
    assert envelope["result"]["count"] == 2, "LMCLIENT_MONGO_URL fallback"
    envelope, _ = error("find", *base, *json_arg("--filter", '{"$bogus":1}'), code=3, expect="SERVER")
    envelope, _ = run("delete", *base, *json_arg("--filter", '{"name":"tea"}'), env=env)
    assert envelope["result"] == {"deleted": 1}, envelope
    envelope, _ = run("delete", *base, "--filter", "{}", env=env)
    assert envelope["result"] == {"deleted": 1}, envelope
    envelope, _ = run("find", *base, env=env)
    assert envelope["result"]["count"] == 0
    if scram:
        # DOCKER-ONLY: a real SCRAM exchange against a server without that user must fail as CONN and
        # never echo the password. The lmmock mongodb mock is auth-less and rejects user configs.
        secret = "DO_NOT_LOG_lmclient_mongo_scram"
        _, process = error("ping", "--url", url, code=3, expect="CONN",
                           env={**env, "LMCLIENT_USER": "nobody", "LMCLIENT_PASSWORD": secret})
        assert secret not in process.stdout + process.stderr

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
    live(preset, scram=True)
    mode = "live via LMCLIENT_MONGO_URL"
else:
    name = "lmclient-mongo-test-" + uuid.uuid4().hex[:8]
    started = False
    try:
        require_docker()
        docker_setup("run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::27017", "mongo:7")
        started = True
        port = published_port(name, "27017/tcp")
        url = f"mongodb://127.0.0.1:{port}"
        wait_ready(url)
        live(url, scram=True)
        mode = "live via docker"
    except DockerUnavailable as exc:
        mode = skip_docker(exc)
    finally:
        if started:
            remove_container(name)
docker_checks = checks

# --- lmmock tier: the released lmmock mongodb mock serves the same live block (no SCRAM) ---
spec = importlib.util.spec_from_file_location('lmmock_helpers', Path(__file__).with_name('lmmock-helpers.py'))
lmmock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lmmock)
lmmock.locate_lmmock()
with lmmock.lmmock_proto('mongodb', {'maxDocuments': 1000}) as url:
    wait_ready(url, seconds=30)
    live(url)
print(f"PASS {checks - docker_checks} lmmock mongodb checks: ping, insert, _id handling, find with equality and $gt, limit, URL fallback, operator rejection, delete")
print(f"lmclient mongo checks: {checks} passed ({'native' if NATIVE else 'JVM'}; {mode}; lmmock tier ran)")
