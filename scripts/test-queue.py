#!/usr/bin/env python3
"""Queue envelope and live RabbitMQ checks. Owns and always removes its container."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from jvm_noise import java_command, strip_jvm_noise
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar'
COMMAND = java_command(artifact)
ENV = {k: v for k, v in os.environ.items() if k not in ('LMCLIENT_USER', 'LMCLIENT_PASSWORD', 'LMCLIENT_QUEUE_URL')}
checks = 0
SECRET = 'dummy-secret-never-print'

def run(*args, code=0, env=None):
    global checks
    p = subprocess.run(COMMAND + ['queue', *args], capture_output=True, text=True, timeout=25, env=env or ENV)
    assert p.returncode == code, (args[0:1], p.returncode, p.stdout, p.stderr)
    assert SECRET not in p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert len(p.stdout.strip().splitlines()) == 1
    assert data['ok'] == (code == 0)
    if code: assert data['error']['code'] == ('USAGE' if code == 2 else 'CONN')
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
    print('queue: SKIP live checks (' + message + ')')
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
        print('queue: WARNING Docker cleanup unavailable for ' + name)

require_docker()

for args in [[], ['unknown'], ['ping'], ['ping', '--url'], ['ping', '--url', 'http://localhost'],
             ['publish', '--url', 'amqp://localhost/', '--queue', 'q'],
             ['consume', '--url', 'amqp://localhost/', '--queue', 'q', '--limit', '0'],
             ['ping', '--url', 'amqp://localhost/', '--timeout', '0'],
             ['ping', '--password', SECRET]]:
    run(*args, code=2)
run('ping', '--url', 'amqp://guest:' + SECRET + '@127.0.0.1:1/', '--timeout', '300', code=3)
name = 'lmclient-queue-' + uuid.uuid4().hex[:10]
try:
    docker_setup('run', '-d', '--name', name, '-e', 'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2',
                 '-p', '127.0.0.1::5672', 'rabbitmq:3-alpine')
    port = published_port(name, '5672/tcp')
    url = f'amqp://guest:guest@127.0.0.1:{port}/'
    for attempt in range(60):
        p = subprocess.run(COMMAND + ['queue', 'ping', '--url', url, '--timeout', '500'], env=ENV,
                           capture_output=True, text=True, timeout=10)
        if p.returncode == 0: break
        time.sleep(1)
    else: raise AssertionError('RabbitMQ did not become ready')
    assert run('ping', env={**ENV, 'LMCLIENT_QUEUE_URL': url})['connected']
    messages = ['first', 'héllo "world"\nsecond', 'third']
    for body in messages:
        assert run('publish', '--url', url, '--queue', 'roundtrip', '--body', body)['published']
    result = run('consume', '--url', url, '--queue', 'roundtrip', '--limit', '3', '--timeout', '2000')
    assert result['messages'] == messages, result
    assert run('consume', '--url', url, '--queue', 'roundtrip', '--timeout', '200')['messages'] == []
    with tempfile.TemporaryDirectory() as directory:
        credentials = Path(directory) / 'credentials.properties'
        credentials.write_text('user=guest\npassword=guest\n')
        assert run('ping', '--url', f'amqp://127.0.0.1:{port}/', '--credentials-file', str(credentials))['connected']
    run('ping', '--url', url, '--timeout', '1000', code=3, env={**ENV, 'LMCLIENT_PASSWORD': SECRET})
    print(f'queue: {checks} checks passed; live publish 3 / consume 3 preserved order and auto-ack')
except DockerUnavailable as exc:
    skip_docker(exc)
finally:
    remove_container(name)
