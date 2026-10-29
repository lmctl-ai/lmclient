#!/usr/bin/env python3
"""Envelope/usage tests and a real SMTP -> IMAP GreenMail round trip.
Usage: python3 scripts/test-mail.py target/lmclient-0.2.0-all.jar
Accepts a native executable too. Only dummy credentials; no external delivery.
Docker absent: usage checks run, live checks print SKIPPED. Containers always removed.
"""
import json
import imaplib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar').resolve()
COMMAND = ['java', '-jar', str(artifact)] if artifact.suffix == '.jar' else [str(artifact)]
ENV = {k: v for k, v in os.environ.items() if not k.startswith('LMCLIENT_MAIL_')}
checks = 0

def run(*args, code=0, env=None):
    global checks
    result = subprocess.run(COMMAND + ['mail'] + list(args), capture_output=True,
                            text=True, encoding='utf-8', timeout=30, env={**ENV, **(env or {})})
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
# A TCP server which never greets the SMTP client proves read timeouts are active.
with socket.socket() as stalled:
    stalled.bind(('127.0.0.1', 0))
    stalled.listen(1)
    started = time.monotonic()
    run('send', '--host', '127.0.0.1', '--port', str(stalled.getsockname()[1]), '--timeout', '250',
        '--from', 'sender@example.test', '--to', 'test@example.test', code=3)
    assert time.monotonic() - started < 5, 'SMTP read timeout not enforced'

if shutil.which('docker') is None:
    print(f'PASS {checks} mail checks; SKIPPED live GreenMail: docker is absent')
    sys.exit(0)
info = subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if info.returncode:
    print(f'PASS {checks} mail checks; SKIPPED live GreenMail: Docker daemon unavailable')
    sys.exit(0)
name = 'lmclient-mail-' + uuid.uuid4().hex[:12]
try:
    started = subprocess.run(['docker', 'run', '-d', '--name', name,
        '-p', '127.0.0.1::3025', '-p', '127.0.0.1::3143',
        '-e', 'GREENMAIL_OPTS=-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.users=test:secret@localhost',
        'greenmail/standalone:2.0.1'], capture_output=True, text=True, timeout=180)
    assert started.returncode == 0, 'GreenMail container startup failed (check Docker/image availability)'
    def port(container_port):
        mapping = subprocess.check_output(['docker', 'port', name, str(container_port)], text=True).strip()
        return mapping.rsplit(':', 1)[1]
    smtp, imap = port(3025), port(3143)
    deadline = time.monotonic() + 60
    while True:
        try:
            with socket.create_connection(('127.0.0.1', int(smtp)), timeout=1) as connection:
                assert connection.recv(1024).startswith(b'220')
            with socket.create_connection(('127.0.0.1', int(imap)), timeout=1) as connection:
                assert connection.recv(1024).startswith(b'* OK')
            break
        except (OSError, AssertionError):
            if time.monotonic() > deadline:
                raise AssertionError('GreenMail did not become ready')
            time.sleep(0.5)
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
        # GreenMail's self-signed certificate must not be silently trusted or downgraded.
        run('read', *common, '--starttls', '--timeout', '1000', env=password, code=3)
        assert run('read', '--url', f'imap://127.0.0.1:{imap}', '--user', 'test', '--limit', '1', env=password)['result']['messages'] == messages[:1]
        assert run('read', '--user', 'test', '--limit', '1', env={**password, 'LMCLIENT_MAIL_URL': f'imap://127.0.0.1:{imap}'})['result']['messages'] == messages[:1]
        run('read', *common, '--credentials-file', str(credentials), env={'LMCLIENT_MAIL_PASSWORD': 'dummy-private-password'}, code=3)
    print(f'PASS {checks} mail checks: GreenMail SMTP delivery, IMAP newest-first headers, UTF-8, limits, URL/env, credentials, auth failure, and timeouts')
finally:
    subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
