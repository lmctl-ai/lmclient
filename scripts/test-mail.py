#!/usr/bin/env python3
"""Envelope/usage tests, lmmock SMTP -> IMAP, and a GreenMail round trip.
Usage: python3 scripts/test-mail.py target/lmclient-0.2.0-all.jar
Accepts a native executable too. Only dummy credentials; no external delivery.
Docker absent: usage and lmmock checks run; GreenMail prints SKIPPED.
Mock children and containers are always reaped before fixture cleanup.
"""
import json
import importlib.util
import imaplib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from jvm_noise import java_command, strip_jvm_noise
import tempfile
import threading
import time
import uuid
from urllib.parse import urlsplit
from temp_cleanup import temporary_directory

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar').resolve()
COMMAND = java_command(artifact)
ENV = {k: v for k, v in os.environ.items() if not k.startswith('LMCLIENT_MAIL_')}
checks = 0

def run(*args, code=0, env=None, process_timeout=30):
    global checks
    result = subprocess.run(COMMAND + ['mail'] + list(args), capture_output=True,
                            text=True, encoding='utf-8', timeout=process_timeout, env={**ENV, **(env or {})})
    assert result.returncode == code, f'mail {args[0] if args else "usage"}: unexpected exit {result.returncode}'
    assert len(result.stdout.splitlines()) == 1, 'expected exactly one JSON envelope'
    envelope = json.loads(result.stdout)
    assert envelope['ok'] == (code == 0), 'wrong envelope ok flag'
    if code:
        assert set(envelope['error']) == {'code', 'message'}
        if code == 2:
            assert envelope['error']['code'] == 'USAGE'
    for secret in ('secret', 'dummy-private-password'):
        assert secret not in result.stdout + result.stderr, 'credential leaked'
    checks += 1
    return envelope

for args in [[], ['unknown'], ['ping'], ['send', '--host', 'localhost'],
             ['read', '--host', 'localhost', '--user', 'test'],
             ['read', '--host', 'localhost', '--user', 'test', '--limit', '0'],
             ['ping', '--host', 'localhost', '--port', '65536'],
             ['ping', '--host', 'localhost', '--timeout', '0'],
             ['ping', '--host', 'localhost', '--password', 'dummy-private-password'],
             ['ping', '--url', 'smtp://test:dummy-private-password@localhost'],
             ['send', '--host', 'localhost', '--from', 'a@example.test', '--to', 'b@example.test', '--body', 'x', '--body-file', 'x'],
             ['read', '--host', 'localhost', '--user', 'test', '--limit', '1', '--ssl', '--starttls']]:
    run(*args, code=2)
with socket.socket() as closed:
    closed.bind(('127.0.0.1', 0))
    unused = closed.getsockname()[1]
run('ping', '--host', '127.0.0.1', '--port', str(unused), '--timeout', '300', code=3)
# Start the clock when the peer accepts, not before JVM/native startup. Keep
# the peer open until the client finishes: server EOF cannot masquerade as a timeout.
# A partial greeting arriving every 50ms defeats an inactivity-only socket timeout.
def check_stalled_peer(protocol, trickle):
    label = protocol + (' trickled greeting' if trickle else ' silent greeting')
    last_timing = ''
    for attempt in range(2):  # One retry for scheduling jitter, not protocol/envelope failures.
        stop = threading.Event()
        ready = threading.Event()
        timeout_seconds = 10  # Includes cold mail/activation initialization before connect.
        accepted_at = []
        peer_errors = []
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(2)
            listener.settimeout(0.2)
            def serve():
                try:
                    # Accept and acknowledge a real probe before the client starts.
                    while not stop.is_set():
                        try:
                            probe, _ = listener.accept()
                            with probe:
                                probe.sendall(b'READY')
                            ready.set()
                            break
                        except socket.timeout:
                            continue
                    while not stop.is_set():
                        try:
                            connection, _ = listener.accept()
                            break
                        except socket.timeout:
                            continue
                    else:
                        return
                    with connection:
                        accepted_at.append(time.monotonic())
                        while not stop.wait(0.05):
                            if trickle:
                                try:
                                    connection.sendall(b'x')  # Never complete the protocol greeting.
                                except OSError:
                                    return
                except OSError:
                    if not stop.is_set():
                        peer_errors.append('fixture socket failed')
            peer = threading.Thread(target=serve, daemon=True)
            peer.start()
            args = ['--host', '127.0.0.1', '--port', str(listener.getsockname()[1]),
                    '--timeout', str(timeout_seconds * 1000)]
            command = (['send', *args, '--from', 'sender@example.test', '--to', 'test@example.test']
                       if protocol == 'SMTP' else ['read', *args, '--user', 'test', '--limit', '1'])
            try:
                with socket.create_connection(listener.getsockname(), timeout=10) as probe:
                    greeting = b''
                    while len(greeting) < 5:
                        chunk = probe.recv(5 - len(greeting))
                        assert chunk, label + ': readiness probe closed'
                        greeting += chunk
                    assert greeting == b'READY', label + ': readiness probe failed'
                assert ready.wait(10), label + ': fixture did not acknowledge readiness'
                try:
                    envelope = run(*command, code=3, env={'LMCLIENT_MAIL_PASSWORD': 'secret'},
                                   process_timeout=60)
                    duration = time.monotonic() - accepted_at[0] if accepted_at else None
                    passed = duration is not None and duration <= 4 * timeout_seconds
                    last_timing = (f"no accepted connection (client error: {envelope['error']['code']})"
                                   if duration is None else f'{duration:.1f}s after accept')
                except subprocess.TimeoutExpired:
                    passed = False
                    last_timing = 'client exceeded 60s process watchdog'
            finally:
                stop.set()
                peer.join(timeout=2)
            assert not peer.is_alive() and not peer_errors, label + ': fixture failed'
            if passed:
                return
            if attempt == 0:
                print('Retrying ' + label + ' timing check: ' + last_timing)
    raise AssertionError(label + ': timeout not enforced (' + last_timing + ')')

for protocol in ('SMTP', 'IMAP'):
    for trickle in (False, True):
        check_stalled_peer(protocol, trickle)

def lmmock_mail_tier():
    spec = importlib.util.spec_from_file_location('lmmock_helpers', Path(__file__).with_name('lmmock-helpers.py'))
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)
    try:
        mock.locate_lmmock()
    except SystemExit as skipped:
        if skipped.code != 0:
            raise
        # Local acquisition failures skip only this tier; keep the existing
        # Docker checks. LMMOCK_REQUIRED=1 raises instead and fails CI.
        return
    before = checks
    with temporary_directory(prefix='lmclient-mail-mock-') as directory:
        root = Path(directory)
        config = {'users': {'test': 'secret'}, 'spool': str(root / 'mail.jsonl')}
        # Two independent processes exchange raw MIME via the shared spool.
        with mock.lmmock_proto('smtp', config) as smtp_url, mock.lmmock_proto('imap', config) as imap_url:
            smtp, imap = urlsplit(smtp_url), urlsplit(imap_url)
            smtp_args = ['--host', smtp.hostname, '--port', str(smtp.port)]
            common = ['--host', imap.hostname, '--port', str(imap.port), '--user', 'test', '--limit', '10']
            password = {'LMCLIENT_MAIL_PASSWORD': 'secret'}
            run('ping', *smtp_args)
            assert run('read', *common, env=password)['result']['messages'] == []
            body = root / 'body.txt'
            body.write_text('Body marker must never be returned by read: BODY_ONLY_123', encoding='utf-8')
            credentials = root / 'mail.properties'
            credentials.write_text('user=test\npassword=secret\n', encoding='utf-8')
            for i, subject in enumerate(['First message', 'Second café 世界']):
                sent = run('send', *smtp_args,
                           '--from', 'sender@example.test', '--to', 'test@localhost,other@example.test',
                           '--subject', subject, '--body-file', str(body),
                           *(['--user', 'test', '--credentials-file', str(credentials)] if i else []), env=password)
                assert sent['result'] == {'sent': True, 'to': ['test@localhost', 'other@example.test']}
            read_args = ['read', '--host', imap.hostname, '--port', str(imap.port),
                         '--limit', '10', '--credentials-file', str(credentials)]
            messages = run(*read_args)['result']['messages']
            assert [message['subject'] for message in messages] == ['Second café 世界', 'First message']
            for message in messages:
                assert set(message) == {'from', 'subject', 'date'}
                assert message['from'] == 'sender@example.test'
                assert message['date'].endswith('Z')
            assert 'BODY_ONLY_123' not in json.dumps(messages)
            with imaplib.IMAP4(imap.hostname, imap.port, timeout=5) as mailbox:
                mailbox.login('test', 'secret')
                mailbox.select('INBOX', readonly=True)
                status, unseen = mailbox.search(None, 'UNSEEN')
                assert status == 'OK' and len(unseen[0].split()) == 2, 'header read marked messages seen'
            assert run('read', '--url', imap_url, '--user', 'test', '--limit', '1', env=password)['result']['messages'] == messages[:1]
            assert run('read', '--user', 'test', '--limit', '1', env={**password, 'LMCLIENT_MAIL_URL': imap_url})['result']['messages'] == messages[:1]
            run('read', *common, '--credentials-file', str(credentials),
                env={'LMCLIENT_MAIL_PASSWORD': 'dummy-private-password'}, code=3)
            # STARTTLS certificate assertions remain Docker-only: lmmock has no TLS.
    print(f'PASS {checks - before} lmmock mail checks: shared-spool SMTP/IMAP, UTF-8, newest-first headers, UNSEEN, limits, URL/env, credentials and auth rejection')


lmmock_mail_tier()

if shutil.which('docker') is None:
    print(f'PASS {checks} mail checks; SKIPPED live GreenMail: docker is absent')
    sys.exit(0)
def diagnostic(text):
    # GreenMail logs can include its configured dummy password.
    for value in ('dummy-private-password', 'secret'):
        text = text.replace(value, '[REDACTED]')
    return text[-8000:]

try:
    info = subprocess.run(['docker', 'info', '--format', '{{.OSType}}'],
                          capture_output=True, text=True, timeout=30)
except (OSError, subprocess.TimeoutExpired):
    info = None
if info is None or info.returncode:
    print(f'PASS {checks} mail checks; SKIPPED live GreenMail: Docker daemon unavailable')
    sys.exit(0)
if info.stdout.strip() != 'linux':
    print(f'PASS {checks} mail checks; SKIPPED live GreenMail: Docker must support Linux containers')
    sys.exit(0)
image = 'greenmail/standalone:2.0.1'
# Pulling is separate from the readiness clock; a cold runner needs more time.
for attempt in range(2):
    try:
        pulled = subprocess.run(['docker', 'pull', image], capture_output=True, text=True, timeout=300)
        pull_error = diagnostic(pulled.stdout + pulled.stderr)
        if pulled.returncode == 0:
            break
    except subprocess.TimeoutExpired:
        pull_error = 'image pull exceeded 300s'
    if attempt == 1:
        raise AssertionError('GreenMail image pull failed: ' + pull_error)
    time.sleep(3)
name = 'lmclient-mail-' + uuid.uuid4().hex[:12]

def container_diagnostics():
    try:
        logs = subprocess.run(['docker', 'logs', '--tail', '100', name],
                              capture_output=True, text=True, timeout=15)
        return diagnostic(logs.stdout + logs.stderr)
    except (OSError, subprocess.TimeoutExpired):
        return 'container logs unavailable'

try:
    try:
        started = subprocess.run(['docker', 'run', '--pull=never', '-d', '--name', name,
            '-p', '127.0.0.1::3025', '-p', '127.0.0.1::3143',
            '-e', 'GREENMAIL_OPTS=-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.users=test:secret@localhost',
            image], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise AssertionError('GreenMail docker run exceeded 120s; logs: ' + container_diagnostics()) from None
    assert started.returncode == 0, ('GreenMail container startup failed: ' +
        diagnostic(started.stdout + started.stderr) + '; logs: ' + container_diagnostics())
    def port(container_port):
        mapping = subprocess.run(['docker', 'port', name, str(container_port)],
                                 capture_output=True, text=True, timeout=10)
        if mapping.returncode or not mapping.stdout.strip():
            raise OSError('port mapping unavailable: ' + diagnostic(mapping.stderr))
        return mapping.stdout.strip().splitlines()[0].rsplit(':', 1)[1]
    deadline = time.monotonic() + 120
    while True:
        try:
            smtp, imap = port(3025), port(3143)
            for published, prefix in ((smtp, b'220'), (imap, b'* OK')):
                with socket.create_connection(('127.0.0.1', int(published)), timeout=2) as connection:
                    greeting = b''
                    while len(greeting) < len(prefix):
                        chunk = connection.recv(len(prefix) - len(greeting))
                        assert chunk, 'greeting closed before ready'
                        greeting += chunk
                    assert greeting == prefix, 'unexpected greeting'
            break
        except (OSError, AssertionError, subprocess.TimeoutExpired) as error:
            if time.monotonic() >= deadline:
                raise AssertionError('GreenMail did not become ready within 120s: ' +
                    diagnostic(str(error)) + '; logs: ' + container_diagnostics()) from None
            time.sleep(1)
    run('ping', '--host', '127.0.0.1', '--port', smtp)
    common = ['--host', '127.0.0.1', '--port', imap, '--user', 'test', '--limit', '10']
    password = {'LMCLIENT_MAIL_PASSWORD': 'secret'}
    assert run('read', *common, env=password)['result']['messages'] == []
    with tempfile.TemporaryDirectory(prefix='lmclient-mail-') as directory:
        body = Path(directory) / 'body.txt'
        body.write_text('Body marker must never be returned by read: BODY_ONLY_123', encoding='utf-8')
        credentials = Path(directory) / 'mail.properties'
        credentials.write_text('user=test\npassword=secret\n', encoding='utf-8')
        for i, subject in enumerate(['First message', 'Second café 世界']):
            sent = run('send', '--host', '127.0.0.1', '--port', smtp,
                       '--from', 'sender@example.test', '--to', 'test@localhost,other@example.test',
                       '--subject', subject, '--body-file', str(body),
                       *(['--user', 'test', '--credentials-file', str(credentials)] if i else []), env=password)
            assert sent['result'] == {'sent': True, 'to': ['test@localhost', 'other@example.test']}
        read_args = ['read', '--host', '127.0.0.1', '--port', imap, '--limit', '10', '--credentials-file', str(credentials)]
        messages = run(*read_args)['result']['messages']
        assert [message['subject'] for message in messages] == ['Second café 世界', 'First message']
        for message in messages:
            assert set(message) == {'from', 'subject', 'date'}
            assert message['from'] == 'sender@example.test'
            assert message['date'].endswith('Z')
        assert 'BODY_ONLY_123' not in json.dumps(messages)
        with imaplib.IMAP4('127.0.0.1', int(imap), timeout=5) as mailbox:
            mailbox.login('test', 'secret')
            mailbox.select('INBOX', readonly=True)
            status, unseen = mailbox.search(None, 'UNSEEN')
            assert status == 'OK' and len(unseen[0].split()) == 2, 'header read marked messages seen'
        # Docker-only: lmmock has no TLS. GreenMail's self-signed certificate
        # must not be silently trusted or downgraded.
        run('read', *common, '--starttls', '--timeout', '1000', env=password, code=3)
        assert run('read', '--url', f'imap://127.0.0.1:{imap}', '--user', 'test', '--limit', '1', env=password)['result']['messages'] == messages[:1]
        assert run('read', '--user', 'test', '--limit', '1', env={**password, 'LMCLIENT_MAIL_URL': f'imap://127.0.0.1:{imap}'})['result']['messages'] == messages[:1]
        run('read', *common, '--credentials-file', str(credentials), env={'LMCLIENT_MAIL_PASSWORD': 'dummy-private-password'}, code=3)
    print(f'PASS {checks} mail checks: GreenMail SMTP delivery, IMAP newest-first headers, UTF-8, limits, URL/env, credentials, auth failure, and timeouts')
finally:
    subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
