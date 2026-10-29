#!/usr/bin/env python3
"""Queue envelope and live RabbitMQ checks. Owns and always removes its container."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar'
COMMAND = ['java', '-jar', str(artifact.resolve())] if artifact.suffix == '.jar' else [str(artifact.resolve())]
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

for args in [[], ['unknown'], ['ping'], ['ping', '--url'], ['ping', '--url', 'http://localhost'],
             ['publish', '--url', 'amqp://localhost/', '--queue', 'q'],
             ['consume', '--url', 'amqp://localhost/', '--queue', 'q', '--limit', '0'],
             ['ping', '--url', 'amqp://localhost/', '--timeout', '0'],
             ['ping', '--password', SECRET]]:
    run(*args, code=2)
run('ping', '--url', 'amqp://guest:' + SECRET + '@127.0.0.1:1/', '--timeout', '300', code=3)
if not shutil.which('docker') or subprocess.run(['docker', 'info'], capture_output=True).returncode:
    print(f'queue: {checks} checks passed; SKIPPED live checks (Docker unavailable)')
    sys.exit(0)
name = 'lmclient-queue-' + uuid.uuid4().hex[:10]
try:
    subprocess.run(['docker', 'run', '-d', '--name', name, '-e', 'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2',
                    '-p', '127.0.0.1::5672', 'rabbitmq:3-alpine'], check=True, capture_output=True, timeout=180)
    port = subprocess.check_output(['docker', 'port', name, '5672/tcp'], text=True).strip().rsplit(':', 1)[1]
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
finally:
    subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
