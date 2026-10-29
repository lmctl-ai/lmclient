#!/usr/bin/env python3
"""Kafka envelope checks, released lmmock tier, and real KRaft round trips."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from jvm_noise import java_command, strip_jvm_noise
import time
import uuid
from urllib.parse import urlsplit
from lmmock_tiers import mock

# Windows Java launcher argv uses CP_ACP; stdout encoding cannot repair it.
# No file input exists for payloads: use portable ASCII argv on Windows,
# retaining Unicode/quoted/newline round trips on Unix in BOTH live tiers.
ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar'
COMMAND = java_command(artifact)
ENV = {k: v for k, v in os.environ.items() if k not in ('LMCLIENT_KAFKA_URL', 'LMDB_KAFKA_URL')}
SECRET = 'dummy-secret-never-print'
checks = 0

def run(*args, code=0, env=None):
    global checks
    p = subprocess.run(COMMAND + ['kafka', *args], capture_output=True, text=True, encoding='utf-8', timeout=25, env=env or ENV)
    assert p.returncode == code, (args[:1], p.returncode, p.stdout, p.stderr)
    assert SECRET not in p.stdout + p.stderr
    assert len(p.stdout.strip().splitlines()) == 1, p.stdout
    data = json.loads(p.stdout)
    assert data['ok'] == (code == 0), data
    if code:
        assert data['error']['code'] == ('USAGE' if code == 2 else 'CONN'), data
    checks += 1
    return data.get('result')

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
    print('kafka: SKIP Docker live checks (' + message + ')')
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
        print('kafka: WARNING Docker cleanup unavailable for ' + name)


for args in [[], ['unknown'], ['ping'], ['ping', '--url'],
             ['ping', '--url', 'http://localhost:9092'],
             ['ping', '--url', 'localhost:99999'],
             ['ping', '--url', 'user:' + SECRET + '@localhost:9092'],
             ['ping', '--url', 'localhost:9092', '--timeout', '0'],
             ['ping', '--url', 'localhost:9092', '--url', 'localhost:9093'],
             ['produce', '--url', 'localhost:9092', '--topic', 't'],
             ['produce', '--url', 'localhost:9092', '--topic', '..', '--message', 'm'],
             ['consume', '--url', 'localhost:9092', '--topic', 't', '--limit', '0'],
             ['consume', '--url', 'localhost:9092', '--topic', 't', '--limit', '10001'],
             ['ping', '--password', SECRET]]:
    run(*args, code=2)
for args in [['ping'], ['produce', '--topic', 't', '--message', SECRET], ['consume', '--topic', 't']]:
    start = time.monotonic()
    run(*args, '--url', '127.0.0.1:1', '--timeout', '300', code=3)
    assert time.monotonic() - start < 10, 'operation exceeded timeout allowance'
print(f'kafka: {checks} offline/timeout checks passed')


def live(url):
    """Identical client assertions for the in-memory broker and real KRaft."""
    assert run('ping', env={**ENV, 'LMCLIENT_KAFKA_URL': url})['connected']
    assert run('ping', '--url', url, env={**ENV, 'LMCLIENT_KAFKA_URL': '127.0.0.1:1'})['connected']
    messages = ['first', ('hello second' if os.name == 'nt' else 'héllo "Kafka"\nsecond'), 'third']
    for message in messages:
        assert run('produce', '--url', url, '--topic', 'roundtrip', '--message', message)['published']
    result = run('consume', '--url', url, '--topic', 'roundtrip', '--limit', '3', '--timeout', '5000')
    assert result['messages'] == messages, result
    assert run('consume', '--url', url, '--topic', 'roundtrip', '--limit', '1')['messages'] == messages[:1]
    assert run('consume', '--url', url, '--topic', 'roundtrip', '--limit', '5', '--timeout', '1500')['messages'] == messages
    assert run('produce', '--url', url, '--topic', 'empty-value', '--message', '')['published']
    assert run('consume', '--url', url, '--topic', 'empty-value')['messages'] == ['']


before = checks
with mock.lmmock_proto('kafka', {'topics': {'roundtrip': 1}}) as base:
    endpoint = urlsplit(base)
    assert endpoint.scheme == 'kafka' and endpoint.hostname and endpoint.port, base
    # KafkaArea accepts host:port rather than the readiness kafka:// URL.
    live(endpoint.netloc)
print(f'kafka lmmock: {checks - before} live checks passed; {checks} including offline/timeout checks')

require_docker()
name = 'lmclient-kafka-' + uuid.uuid4().hex[:10]
try:
    # Docker selects the host port. Delay Kafka startup until its advertised
    # listener can use that exact mapping, avoiding bind/release port races.
    docker_setup('run', '-d', '--name', name,
                    '-p', '127.0.0.1::9092',
                    '-e', 'KAFKA_NODE_ID=1',
                    '-e', 'KAFKA_PROCESS_ROLES=broker,controller',
                    '-e', 'KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093',
                    '-e', 'KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT',
                    '-e', 'KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER',
                    '-e', 'KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093',
                    '-e', 'KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1',
                    '-e', 'KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1',
                    '-e', 'KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1',
                    'apache/kafka:3.9.1', 'sh', '-c',
                    'while [ ! -s /tmp/lmclient-listener ]; do sleep 0.1; done; '
                    'export KAFKA_ADVERTISED_LISTENERS="$(cat /tmp/lmclient-listener)"; '
                    'exec /etc/kafka/docker/run')
    port = published_port(name, '9092/tcp')
    url = f'127.0.0.1:{port}'
    docker_setup('exec', name, 'sh', '-c',
                 'printf "%s" "$1" > /tmp/lmclient-listener.tmp && '
                 'mv /tmp/lmclient-listener.tmp /tmp/lmclient-listener',
                 'sh', f'PLAINTEXT://{url}', timeout=30)
    for attempt in range(60):
        state = subprocess.check_output(['docker', 'inspect', '-f', '{{.State.Running}}', name], text=True, encoding='utf-8', timeout=10).strip()
        assert state == 'true', 'Kafka container exited before becoming ready'
        p = subprocess.run(COMMAND + ['kafka', 'ping', '--url', url, '--timeout', '3000'],
                           env=ENV, capture_output=True, text=True, encoding='utf-8', timeout=10)
        if p.returncode == 0:
            break
        time.sleep(1)
    else:
        raise AssertionError('Kafka did not become ready')
    before = checks
    live(url)
    print(f'kafka Docker: {checks - before} live checks passed; {checks} total including offline and lmmock')
except DockerUnavailable as exc:
    skip_docker(exc)
finally:
    remove_container(name)
