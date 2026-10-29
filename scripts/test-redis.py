#!/usr/bin/env python3
"""Envelope/usage checks plus real Redis containers; accepts a shaded jar or native binary."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar'
COMMAND = ['java', '-jar', str(TARGET)] if TARGET.suffix == '.jar' else [str(TARGET)]
BASE_ENV = {k: v for k, v in os.environ.items() if not k.startswith(('LMCLIENT_', 'LMDB_'))}
SECRET = 'dummy-redis-pass:+@/测试'
WRONG = 'dummy-wrong-redis-password'
checks = 0
containers = []


def run(*args, code=0, error=None, env=None):
    global checks
    process = subprocess.run(COMMAND + ['redis'] + list(args), capture_output=True,
                             text=True, encoding='utf-8', timeout=20,
                             env={**BASE_ENV, **(env or {})})
    assert process.returncode == code, ('unexpected exit', process.returncode, code)
    assert len(process.stdout.strip().splitlines()) == 1, 'stdout must contain one JSON envelope'
    envelope = json.loads(process.stdout)
    assert envelope['ok'] is (code == 0)
    if error:
        assert envelope['error']['code'] == error
    for secret in (SECRET, WRONG, quote(SECRET, safe='')):
        assert secret not in process.stdout + process.stderr, 'credential leaked'
    checks += 1
    return envelope.get('result', envelope.get('error'))


for args in [[], ['wat'], ['get'], ['ping', 'extra'], ['del'], ['set', 'k'],
             ['lpush', 'k'], ['rpop'], ['lrange', 'k', 'x', '0'], ['publish', 'c'],
             ['set', 'k', 'v', '--ttl', '0'], ['set', 'k', 'v', '--ttl', '-1'],
             ['get', 'k', '--ttl', '1'], ['ping', '--timeout', '0'],
             ['ping', '--timeout', 'huge'], ['ping', '--unknown'], ['ping', '--url'],
             ['ping', '--url', 'http://localhost'], ['ping', '--url', 'redis://localhost/x'],
             ['ping', '--url', 'redis://localhost:65536'], ['ping', '--password', WRONG]]:
    run(*args, code=2, error='USAGE')
for args in [['set', 'k', 'v'], ['del', 'k'], ['lpush', 'k', 'v'], ['rpop', 'k'], ['publish', 'c', 'v']]:
    run(*args, '--url', 'redis://127.0.0.1:1', '--readonly', code=3, error='READONLY')

# A connected but silent peer checks read timeout independently of Docker.
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(10)
    done = threading.Event()
    def silent_peer():
        with listener.accept()[0] as peer:
            done.wait(10)
    worker = threading.Thread(target=silent_peer, daemon=True)
    worker.start()
    try:
        start = time.monotonic()
        run('ping', '--url', f'redis://127.0.0.1:{listener.getsockname()[1]}', '--timeout', '100',
            code=3, error='CONN')
        assert time.monotonic() - start < 8, 'socket timeout not enforced'
    finally:
        done.set()
        worker.join(11)

if not shutil.which('docker'):
    print(f'Redis: {checks} checks passed; SKIPPED live checks (docker absent)')
    sys.exit(0)
if subprocess.run(['docker', 'info'], capture_output=True, timeout=20).returncode:
    print(f'Redis: {checks} checks passed; SKIPPED live checks (docker daemon unavailable)')
    sys.exit(0)


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True,
                          text=True, encoding='utf-8', timeout=120).stdout.strip()


def start_redis(password=None):
    name = 'lmclient-redis-' + uuid.uuid4().hex[:10]
    containers.append(name)
    args = ['run', '-d', '--name', name, '-p', '127.0.0.1::6379', 'redis:7-alpine',
            'redis-server', '--save', '', '--appendonly', 'no']
    if password:
        args += ['--requirepass', password]
    docker(*args)
    port = int(docker('port', name, '6379/tcp').rsplit(':', 1)[1])
    for _ in range(60):
        command = ['exec'] + (['-e', 'REDISCLI_AUTH=' + password] if password else [])
        command += [name, 'redis-cli', 'ping']
        if docker(*command) == 'PONG':
            return name, port
        time.sleep(0.2)
    raise AssertionError('Redis container did not become ready')


try:
    name, port = start_redis()
    url = f'redis://127.0.0.1:{port}/0'
    env = {'LMCLIENT_REDIS_URL': url}
    assert run('ping', env=env) == {'pong': 'PONG'}
    assert run('--url', url, 'ping', '--readonly') == {'pong': 'PONG'}
    assert run('get', 'missing', env=env) == {'value': None}
    value = 'héllo 世界\n"quoted"\\\t'
    assert run('set', 'key', value, env=env) == {'stored': True}
    assert run('get', 'key', env=env) == {'value': value}
    assert run('set', '--', '--literal-key', '--literal-value', env=env) == {'stored': True}
    assert run('get', '--', '--literal-key', env=env) == {'value': '--literal-value'}
    assert run('set', 'temporary', 'gone', '--ttl', '1', env=env) == {'stored': True}
    time.sleep(1.2)
    assert run('get', 'temporary', env=env) == {'value': None}
    assert run('set', 'key', 'database-one', '--url', url[:-1] + '1', env=env) == {'stored': True}
    assert run('get', 'key', env=env) == {'value': value}
    assert run('del', 'key', 'missing', env=env) == {'deleted': 1}
    assert run('del', 'key', env=env) == {'deleted': 0}
    assert run('rpop', 'list', env=env) == {'value': None}
    assert run('lpush', 'list', 'one', 'two', '三', env=env) == {'length': 3}
    assert run('lrange', 'list', '0', '-1', env=env) == {'values': ['三', 'two', 'one']}
    assert run('rpop', 'list', env=env) == {'value': 'one'}
    assert run('lrange', 'list', '10', '20', env=env) == {'values': []}
    run('get', 'list', env=env, code=3, error='CONN')
    assert run('publish', 'news', 'no-listeners', env=env) == {'receivers': 0}
    # Subscribe with RESP directly, then verify lmclient really publishes a message.
    with socket.create_connection(('127.0.0.1', port), timeout=5) as subscriber:
        subscriber.sendall(b'*2\r\n$9\r\nSUBSCRIBE\r\n$4\r\nnews\r\n')
        stream = subscriber.makefile('rb')
        assert [stream.readline() for _ in range(6)] == [b'*3\r\n', b'$9\r\n', b'subscribe\r\n', b'$4\r\n', b'news\r\n', b':1\r\n']
        assert run('publish', 'news', 'hello', env=env) == {'receivers': 1}
        assert [stream.readline() for _ in range(7)] == [b'*3\r\n', b'$7\r\n', b'message\r\n', b'$4\r\n', b'news\r\n', b'$5\r\n', b'hello\r\n']
        stream.close()
    # Replica rejection uses Redis' real READONLY response.
    docker('exec', name, 'redis-cli', 'REPLICAOF', '127.0.0.1', '1')
    run('set', 'replica-key', 'v', env=env, code=3, error='READONLY')
    protected, protected_port = start_redis(SECRET)
    protected_url = f'redis://127.0.0.1:{protected_port}/0'
    protected_env = {'LMCLIENT_REDIS_URL': protected_url}
    run('ping', env=protected_env, code=3, error='CONN')
    run('ping', env={**protected_env, 'LMCLIENT_REDIS_PASSWORD': WRONG}, code=3, error='CONN')
    assert run('ping', env={**protected_env, 'LMCLIENT_REDIS_PASSWORD': SECRET}) == {'pong': 'PONG'}
    assert run('ping', env={**protected_env, 'LMCLIENT_PASSWORD': SECRET}) == {'pong': 'PONG'}
    with tempfile.TemporaryDirectory(prefix='lmclient-redis-credentials-') as directory:
        credentials = Path(directory) / 'redis.properties'
        credentials.write_text('password=' + SECRET + '\n', encoding='utf-8')
        assert run('ping', '--credentials-file', str(credentials), env=protected_env) == {'pong': 'PONG'}
        run('ping', '--credentials-file', str(credentials), env={**protected_env, 'LMCLIENT_PASSWORD': WRONG}, code=3, error='CONN')
    embedded = f'redis://:{quote(SECRET, safe="")}@127.0.0.1:{protected_port}/0'
    assert run('ping', env={'LMCLIENT_REDIS_URL': embedded}) == {'pong': 'PONG'}
    run('ping', env={'LMCLIENT_REDIS_URL': embedded, 'LMCLIENT_REDIS_PASSWORD': WRONG}, code=3, error='CONN')
    print(f'Redis: {checks} checks passed, including live key/value, TTL, lists, publish, auth, replica, and timeouts')
finally:
    for name in containers:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
