#!/usr/bin/env python3
"""MQTT envelope, lmmock and live pub/sub checks. Owns and always removes its container."""
import contextlib
import select
import socket
import threading
from urllib.parse import urlsplit
from lmmock_tiers import mock
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
    print('mqtt: SKIP Docker live checks (' + message + ')')
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
        print('mqtt: WARNING Docker cleanup unavailable for ' + name)


for args in [[], ['unknown'], ['ping'], ['ping', '--url'], ['ping', '--url', 'http://localhost'],
             ['pub', '--url', 'tcp://localhost:1883', '--topic', 'a'],
             ['pub', '--url', 'tcp://localhost:1883', '--topic', '#', '--message', 'x'],
             ['sub', '--url', 'tcp://localhost:1883', '--topic', 'a/#/b'],
             ['sub', '--url', 'tcp://localhost:1883', '--topic', 'a', '--limit', '-1'],
             ['pub', '--url', 'tcp://localhost:1883', '--topic', 'a', '--message', 'x', '--qos', '3'],
             ['ping', '--url', 'tcp://localhost:1883', '--timeout', '0'], ['ping', '--password', SECRET]]:
    run(*args, code=2)
run('ping', '--url', 'tcp://127.0.0.1:1', '--timeout', '300', code=3, env={**ENV, 'LMCLIENT_PASSWORD': SECRET})

@contextlib.contextmanager
def subscription_proxy(url):
    """Forward the subscriber unchanged; observe its broker SUBACK, not a sleep.

    lmmock intentionally emits no broker logs. Parsing only MQTT frame boundaries
    lets the test observe readiness without replacing either client or broker.
    """
    endpoint = urlsplit(url)
    subscribed, stop = threading.Event(), threading.Event()
    errors = []
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(.2)

        def relay():
            try:
                while not stop.is_set():
                    try:
                        downstream, _ = listener.accept()
                        break
                    except socket.timeout:
                        continue
                else:
                    return
                with downstream, socket.create_connection((endpoint.hostname, endpoint.port), timeout=5) as upstream:
                    downstream.settimeout(5)
                    buffered = bytearray()
                    while not stop.is_set():
                        readable, _, _ = select.select([downstream, upstream], [], [], .2)
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (upstream if source is downstream else downstream).sendall(data)
                            if source is upstream:
                                buffered.extend(data)
                                while len(buffered) >= 2:
                                    length, multiplier, end = 0, 1, 1
                                    while end < len(buffered):
                                        digit = buffered[end]
                                        length += (digit & 127) * multiplier
                                        end += 1
                                        if digit < 128:
                                            break
                                        assert end <= 4, 'invalid MQTT frame length'
                                        multiplier *= 128
                                    else:
                                        break
                                    if len(buffered) < end + length:
                                        break
                                    if buffered[0] == 0x90:
                                        assert length >= 3 and all(q in (0, 1, 2) for q in buffered[end + 2:end + length]), 'subscription rejected'
                                        subscribed.set()
                                    del buffered[:end + length]
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=relay, daemon=True)
        worker.start()
        try:
            yield f'tcp://127.0.0.1:{listener.getsockname()[1]}', subscribed
            assert not errors, 'MQTT readiness relay failed'
        finally:
            stop.set()
            worker.join(6)
            assert not worker.is_alive(), 'MQTT readiness relay did not stop'


def mock_tier():
    before = checks
    with mock.lmmock_proto('mqtt') as ready_url:
        assert ready_url.startswith('mqtt://'), 'unexpected MQTT readiness scheme'
        url = 'tcp://' + ready_url.removeprefix('mqtt://')
        assert run('ping', env={**ENV, 'LMCLIENT_MQTT_URL': url})['connected']
        topic = 'lmclient/' + uuid.uuid4().hex
        with subscription_proxy(url) as (subscriber_url, subscribed):
            child = subprocess.Popen(COMMAND + ['mqtt', 'sub', '--url', subscriber_url, '--topic', topic,
                                     '--limit', '3', '--qos', '2', '--timeout', '15000'], env=ENV,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            try:
                assert subscribed.wait(10), 'mock subscription did not receive SUBACK'
                messages = ['first', 'héllo "world"\nsecond', 'third']
                for qos, payload in enumerate(messages):
                    assert run('pub', '--url', url, '--topic', topic, '--message', payload, '--qos', str(qos))['published']
                stdout, stderr = child.communicate(timeout=20)
                result = envelope(subprocess.CompletedProcess([], child.returncode, stdout, stderr))
                assert result['messages'] == [{'topic': topic, 'payload': p} for p in messages], result
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate()
        assert run('sub', '--url', url, '--topic', topic, '--timeout', '1500')['messages'] == []
    with mock.lmmock_proto('mqtt', {'users': {'tester': SECRET}}) as ready_url:
        url = 'tcp://' + ready_url.removeprefix('mqtt://')
        run('ping', '--url', url, '--timeout', '1500', code=3)
        run('ping', '--url', url, '--timeout', '1500', code=3,
            env={**ENV, 'LMCLIENT_USER': 'tester', 'LMCLIENT_PASSWORD': 'wrong-' + SECRET})
        assert run('ping', '--url', url,
                   env={**ENV, 'LMCLIENT_USER': 'tester', 'LMCLIENT_PASSWORD': SECRET})['connected']
        with tempfile.TemporaryDirectory() as directory:
            credentials = Path(directory) / 'mqtt.properties'
            credentials.write_text('user=tester\npassword=' + SECRET + '\n', encoding='utf-8')
            assert run('ping', '--url', url, '--credentials-file', str(credentials))['connected']
    print(f'mqtt lmmock: {checks - before} checks passed; QoS 0/1/2, empty subscription and authentication')


print(f'mqtt: {checks} offline checks passed')
mock_tier()
require_docker()
before = checks
name = 'lmclient-mqtt-' + uuid.uuid4().hex[:10]
subscriber = None
try:
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / 'mosquitto.conf'
        config.write_text('listener 1883\nallow_anonymous true\nlog_type all\n')
        # docker cp avoids host bind-mount permission differences across platforms.
        docker_setup('create', '--name', name, '-p', '127.0.0.1::1883', 'eclipse-mosquitto:2')
        docker_setup('cp', str(config), name + ':/mosquitto/config/mosquitto.conf', timeout=60)
        docker_setup('start', name, timeout=60)
    port = published_port(name, '1883/tcp')
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
    print(f'mqtt Docker: {checks - before} live checks passed; {checks} total; QoS 0/1/2 payloads delivered in order')
except DockerUnavailable as exc:
    skip_docker(exc)
finally:
    if subscriber is not None and subscriber.poll() is None:
        subscriber.kill()
        subscriber.communicate()
    remove_container(name)
