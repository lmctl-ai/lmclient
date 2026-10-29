#!/usr/bin/env python3
"""Kafka envelope and local KRaft round-trip checks; owns its temporary container."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar'
COMMAND = ['java', '-jar', str(artifact.resolve())] if artifact.suffix == '.jar' else [str(artifact.resolve())]
ENV = {k: v for k, v in os.environ.items() if k != 'LMCLIENT_KAFKA_URL'}
SECRET = 'dummy-secret-never-print'
checks = 0

def run(*args, code=0, env=None):
    global checks
    p = subprocess.run(COMMAND + ['kafka', *args], capture_output=True, text=True, timeout=25, env=env or ENV)
    assert p.returncode == code, (args[:1], p.returncode, p.stdout, p.stderr)
    assert SECRET not in p.stdout + p.stderr
    assert len(p.stdout.strip().splitlines()) == 1, p.stdout
    data = json.loads(p.stdout)
    assert data['ok'] == (code == 0), data
    if code:
        assert data['error']['code'] == ('USAGE' if code == 2 else 'CONN'), data
    checks += 1
    return data.get('result')

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
if not shutil.which('docker') or subprocess.run(['docker', 'info'], capture_output=True, timeout=20).returncode:
    print(f'kafka: {checks} checks passed; SKIPPED live checks (Docker unavailable)')
    sys.exit(0)
name = 'lmclient-kafka-' + uuid.uuid4().hex[:10]
with socket.socket() as reservation:
    reservation.bind(('127.0.0.1', 0))
    port = reservation.getsockname()[1]
url = f'127.0.0.1:{port}'
try:
    subprocess.run(['docker', 'run', '-d', '--name', name,
                    '-p', f'127.0.0.1:{port}:9092',
                    '-e', f'KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://{url}',
                    '-e', 'KAFKA_NODE_ID=1',
                    '-e', 'KAFKA_PROCESS_ROLES=broker,controller',
                    '-e', 'KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093',
                    '-e', 'KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT',
                    '-e', 'KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER',
                    '-e', 'KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093',
                    '-e', 'KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1',
                    '-e', 'KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1',
                    '-e', 'KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1',
                    'apache/kafka:3.9.1'], check=True, capture_output=True, timeout=180)
    for attempt in range(60):
        state = subprocess.check_output(['docker', 'inspect', '-f', '{{.State.Running}}', name], text=True, timeout=10).strip()
        assert state == 'true', 'Kafka container exited before becoming ready'
        p = subprocess.run(COMMAND + ['kafka', 'ping', '--url', url, '--timeout', '3000'],
                           env=ENV, capture_output=True, text=True, timeout=10)
        if p.returncode == 0:
            break
        time.sleep(1)
    else:
        raise AssertionError('Kafka did not become ready')
    assert run('ping', env={**ENV, 'LMCLIENT_KAFKA_URL': url})['connected']
    assert run('ping', '--url', url, env={**ENV, 'LMCLIENT_KAFKA_URL': '127.0.0.1:1'})['connected']
    messages = ['first', 'héllo "Kafka"\nsecond', 'third']
    for message in messages:
        assert run('produce', '--url', url, '--topic', 'roundtrip', '--message', message)['published']
    result = run('consume', '--url', url, '--topic', 'roundtrip', '--limit', '3', '--timeout', '5000')
    assert result['messages'] == messages, result
    assert run('consume', '--url', url, '--topic', 'roundtrip', '--limit', '1')['messages'] == messages[:1]
    assert run('consume', '--url', url, '--topic', 'roundtrip', '--limit', '5', '--timeout', '1500')['messages'] == messages
    assert run('produce', '--url', url, '--topic', 'empty-value', '--message', '')['published']
    assert run('consume', '--url', url, '--topic', 'empty-value')['messages'] == ['']
    print(f'kafka: {checks} checks passed; live ping / produce 3 / consume 3 preserved order; replay and partial timeout verified')
finally:
    subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
