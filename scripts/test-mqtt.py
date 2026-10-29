#!/usr/bin/env python3
"""MQTT envelope and live pub/sub checks. Owns and always removes its container."""
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
ENV = {k: v for k, v in os.environ.items() if k not in ('LMCLIENT_USER', 'LMCLIENT_PASSWORD', 'LMCLIENT_MQTT_URL')}
checks = 0
SECRET = 'dummy-secret-never-print'

def envelope(p, code=0):
    global checks
    assert p.returncode == code, (p.returncode, p.stdout, p.stderr)
    assert SECRET not in p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert len(p.stdout.strip().splitlines()) == 1
    assert data['ok'] == (code == 0)
    if code: assert data['error']['code'] == ('USAGE' if code == 2 else 'CONN')
    checks += 1
    return data.get('result')

def run(*args, code=0, env=None):
    return envelope(subprocess.run(COMMAND + ['mqtt', *args], capture_output=True, text=True,
                                   timeout=25, env=env or ENV), code)

for args in [[], ['unknown'], ['ping'], ['ping', '--url'], ['ping', '--url', 'http://localhost'],
             ['pub', '--url', 'tcp://localhost:1883', '--topic', 'a'],
             ['pub', '--url', 'tcp://localhost:1883', '--topic', '#', '--message', 'x'],
             ['sub', '--url', 'tcp://localhost:1883', '--topic', 'a/#/b'],
             ['sub', '--url', 'tcp://localhost:1883', '--topic', 'a', '--limit', '-1'],
             ['pub', '--url', 'tcp://localhost:1883', '--topic', 'a', '--message', 'x', '--qos', '3'],
             ['ping', '--url', 'tcp://localhost:1883', '--timeout', '0'], ['ping', '--password', SECRET]]:
    run(*args, code=2)
run('ping', '--url', 'tcp://127.0.0.1:1', '--timeout', '300', code=3, env={**ENV, 'LMCLIENT_PASSWORD': SECRET})
if not shutil.which('docker') or subprocess.run(['docker', 'info'], capture_output=True).returncode:
    print(f'mqtt: {checks} checks passed; SKIPPED live checks (Docker unavailable)')
    sys.exit(0)
name = 'lmclient-mqtt-' + uuid.uuid4().hex[:10]
subscriber = None
try:
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / 'mosquitto.conf'
        config.write_text('listener 1883\nallow_anonymous true\nlog_type all\n')
        # docker cp avoids host bind-mount permission differences across platforms.
        subprocess.run(['docker', 'create', '--name', name, '-p', '127.0.0.1::1883', 'eclipse-mosquitto:2'],
                       check=True, capture_output=True, timeout=180)
        subprocess.run(['docker', 'cp', str(config), name + ':/mosquitto/config/mosquitto.conf'], check=True, capture_output=True)
        subprocess.run(['docker', 'start', name], check=True, capture_output=True)
    port = subprocess.check_output(['docker', 'port', name, '1883/tcp'], text=True).strip().rsplit(':', 1)[1]
    url = f'tcp://127.0.0.1:{port}'
    for attempt in range(30):
        p = subprocess.run(COMMAND + ['mqtt', 'ping', '--url', url, '--timeout', '500'], env=ENV,
                           capture_output=True, text=True, timeout=10)
        if p.returncode == 0: break
        time.sleep(1)
    else: raise AssertionError('Mosquitto did not become ready')
    assert run('ping', env={**ENV, 'LMCLIENT_MQTT_URL': url})['connected']
    topic = 'lmclient/' + uuid.uuid4().hex
    subscriber = subprocess.Popen(COMMAND + ['mqtt', 'sub', '--url', url, '--topic', topic, '--limit', '3',
                                              '--qos', '2', '--timeout', '15000'], env=ENV,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # Observe the broker's SUBSCRIBE log instead of racing an arbitrary sleep.
    for attempt in range(100):
        logs = subprocess.run(['docker', 'logs', name], capture_output=True, text=True)
        if topic in logs.stdout + logs.stderr: break
        assert subscriber.poll() is None, 'subscriber exited before subscription'
        time.sleep(.1)
    else: raise AssertionError('subscription did not become ready')
    messages = ['first', 'héllo "world"\nsecond', 'third']
    for qos, payload in enumerate(messages):
        assert run('pub', '--url', url, '--topic', topic, '--message', payload, '--qos', str(qos))['published']
    stdout, stderr = subscriber.communicate(timeout=20)
    result = envelope(subprocess.CompletedProcess([], subscriber.returncode, stdout, stderr))
    assert result['messages'] == [{'topic': topic, 'payload': p} for p in messages], result
    assert run('sub', '--url', url, '--topic', topic, '--timeout', '1500')['messages'] == []
    print(f'mqtt: {checks} checks passed; live pub/sub delivered QoS 0/1/2 payloads in order')
finally:
    if subscriber is not None and subscriber.poll() is None:
        subscriber.kill()
        subscriber.communicate()
    subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
