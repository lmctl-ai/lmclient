#!/usr/bin/env python3
"""Offline HTTP/OAuth checks against a local Python ThreadingHTTPServer.
Run: python3 scripts/test-http.py target/lmclient-0.2.0-all.jar
Also accepts a native executable. Seeds the shared SQLite schema directly;
no dependency on the concurrently developed cred CLI, Docker, or external APIs.
"""
import base64
import datetime
import http.server
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar').resolve()
COMMAND = ['java', '-jar', str(artifact)] if artifact.suffix == '.jar' else [str(artifact)]
state = {'requests': [], 'tokens': [], 'reply': {}, 'token_status': 200}
SECRETS = ['stored-private', 'environment-private', 'old-access-private', 'fresh-access-private',
           'refresh-private', 'rotated-private', 'client-private', 'custom-private']

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass
    def respond(self, status, body, content_type='application/json', headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            if self.command != 'HEAD':
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
    def do_GET(self):
        body = self.rfile.read(int(self.headers.get('content-length', '0'))).decode()
        request = {'method': self.command, 'headers': {key.title(): value for key, value in self.headers.items()}, 'body': body, 'path': self.path}
        state['requests'].append(request)
        if self.path == '/token':
            state['tokens'].append(request)
            self.respond(state['token_status'], state['reply'])
        elif self.path == '/redirect':
            self.respond(302, b'', headers={'Location': '/echo'})
        elif self.path == '/limited':
            self.respond(429, {'error': 'rate limited'})
        elif self.path == '/missing':
            self.respond(404, {'error': 'missing'})
        elif self.path == '/large':
            self.respond(200, b'x' * (10 * 1024 * 1024 + 1), 'text/plain')
        elif self.path == '/slow-body':
            self.send_response(200)
            self.send_header('Content-Length', '4')
            self.end_headers()
            self.wfile.flush()
            time.sleep(2)
            try:
                self.wfile.write(b'late')
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == '/text':
            self.respond(200, b'plain response', 'text/plain')
        elif self.path == '/null':
            self.respond(200, b'null')
        elif self.path == '/escaped':
            token = self.headers.get('Authorization', '').removeprefix('Bearer ')
            self.respond(200, {token: ['quote " slash \\ ' + token]})
        else:
            self.respond(200, request)
    do_POST = do_GET
    do_PUT = do_GET
    do_HEAD = do_GET

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f'http://127.0.0.1:{server.server_port}'
checks = 0
try:
    with tempfile.TemporaryDirectory(prefix='lmclient-http-') as directory:
        db = str(Path(directory) / 'creds.db')
        env = {**os.environ, 'LMCLIENT_DB': db}
        env.pop('HTTP_TEST_API_KEY', None)
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE creds(service TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(service,field))')
        def seed(service, values):
            with sqlite3.connect(db) as connection:
                for field, value in values.items():
                    connection.execute('INSERT OR REPLACE INTO creds VALUES(?,?,?,?)', (service, field, value, '2026-01-01T00:00:00Z'))
        def stored(service, field):
            with sqlite3.connect(db) as connection:
                row = connection.execute('SELECT value FROM creds WHERE service=? AND field=?', (service, field)).fetchone()
                return row[0] if row else None
        def run(*args, code=0, extra_env=None):
            global checks
            p = subprocess.run(COMMAND + ['http'] + list(args), capture_output=True, text=True,
                               encoding='utf-8', timeout=20, env={**env, **(extra_env or {})})
            assert p.returncode == code, f'HTTP check {checks + 1}: expected exit {code}, got {p.returncode}; {p.stdout}'
            assert len(p.stdout.splitlines()) == 1, 'stdout must have one envelope'
            for secret in SECRETS:
                assert secret not in p.stdout + p.stderr, 'secret leaked'
            value = json.loads(p.stdout)
            assert value['ok'] == (code == 0)
            if code == 2:
                assert value['error']['code'] == 'USAGE'
            checks += 1
            return value.get('result') if code == 0 else value['error']

        for args in [[], ['get'], ['request'], ['request', 'ftp://localhost/'], ['request', 'bad-url'],
                     ['request', base, '--unknown'], ['request', base, '--timeout', '0'],
                     ['request', base, '--header', 'bad'], ['request', base, '--method'],
                     ['request', base, '--data', 'x', '--data-file', 'x'],
                     ['request', base, '--header', 'X-Test: bad\r\ninjected: value'],
                     ['request', base, '--data-file', str(Path(directory) / 'absent')]]:
            run(*args, code=2)
        result = run('request', base + '/echo', '--header', 'X-Echo: first', '--header', 'X-Echo: second')
        assert {'status', 'ok', 'contentType', 'latencyMs', 'url', 'bodyJson'} == set(result)
        assert result['status'] == 200 and result['ok'] is True and result['latencyMs'] >= 0
        assert result['bodyJson']['headers']['X-Echo'] == 'first, second'
        result = run('request', base + '/echo', '--data', '{"a":1}')
        assert result['bodyJson']['method'] == 'POST'
        assert result['bodyJson']['headers']['Content-Type'] == 'application/json'
        assert json.loads(result['bodyJson']['body']) == {'a': 1}
        data_file = Path(directory) / 'body.txt'
        data_file.write_text('héllo 世界', encoding='utf-8')
        result = run('request', base + '/echo', '--method', 'put', '--data-file', str(data_file))
        assert result['bodyJson']['method'] == 'PUT' and result['bodyJson']['body'] == 'héllo 世界'
        assert result['bodyJson']['headers']['Content-Type'].startswith('text/plain')
        assert run('request', base + '/echo', '--method', 'GET', '--data', 'ignored')['bodyJson']['body'] == ''
        assert run('request', base + '/text')['bodyText'] == 'plain response'
        assert run('request', base + '/null')['bodyJson'] is None
        assert run('request', base + '/echo', '--method', 'HEAD')['bodyText'] == ''
        assert run('request', base + '/missing')['ok'] is False
        before = len(state['requests'])
        assert run('request', base + '/redirect')['status'] == 302
        assert len(state['requests']) == before + 1, 'followed a redirect'
        before = len(state['requests'])
        assert run('request', base + '/limited')['status'] == 429
        assert len(state['requests']) == before + 1, 'retried 429'
        seed('http-test', {'api_key': 'stored-private', 'oauth_access_token': 'old-access-private', 'oauth_expires_at': '2000-01-01T00:00:00Z'})
        result = run('request', base + '/echo', '--auth', 'http-test', extra_env={'HTTP_TEST_API_KEY': 'environment-private'})
        assert state['requests'][-1]['headers']['Authorization'] == 'Bearer stored-private'
        assert result['keySource'] == 'store'
        assert result['bodyJson']['headers']['Authorization'] == 'Bearer [REDACTED]'
        seed('http-test', {'api_key': ''})
        result = run('request', base + '/echo', '--auth', 'http-test', extra_env={'HTTP_TEST_API_KEY': 'environment-private'})
        assert result['keySource'] == 'env:HTTP_TEST_API_KEY'
        assert state['requests'][-1]['headers']['Authorization'] == 'Bearer environment-private'
        result = run('request', base + '/echo', '--header', 'Authorization: Bearer custom-private')
        assert '[REDACTED]' in result['bodyJson']['headers']['Authorization']
        missing = run('request', base, '--auth', 'unconfigured-http-test', code=3)
        assert missing['code'] == 'MISSING_KEY' and 'cred set' in missing['message'] and 'oauth authorize' in missing['message']

        def oauth(service, style='header', expired=True, refresh=True):
            values = {'oauth_access_token': 'old-access-private', 'oauth_expires_at': '2000-01-01T00:00:00Z' if expired else '2099-01-01T00:00:00Z',
                      'oauth_token_url': base + '/token', 'oauth_client_id': 'test-client', 'oauth_client_secret': 'client-private'}
            if style:
                values['oauth_auth_style'] = style
            if refresh:
                values['oauth_refresh_token'] = 'refresh-private'
            seed(service, values)
            state['reply'] = {'access_token': 'fresh-access-private', 'expires_in': 3600, 'token_type': 'Bearer'}
            state['token_status'] = 200
            state['tokens'].clear()
        oauth('valid', expired=False)
        assert run('request', base + '/escaped', '--auth', 'valid')['bodyJson'] == {'[REDACTED]': ['quote " slash \\ [REDACTED]']}
        assert not state['tokens']
        oauth('expired', style=None)
        result = run('request', base + '/echo', '--auth', 'expired')
        assert result['keySource'] == 'store-oauth' and len(state['tokens']) == 1
        token_request = state['tokens'][0]
        assert token_request['headers']['Authorization'] == 'Basic ' + base64.b64encode(b'test-client:client-private').decode()
        assert urllib.parse.parse_qs(token_request['body']) == {'grant_type': ['refresh_token'], 'refresh_token': ['refresh-private']}
        assert state['requests'][-1]['headers']['Authorization'] == 'Bearer fresh-access-private'
        assert stored('expired', 'oauth_refresh_token') == 'refresh-private'
        assert stored('expired', 'oauth_access_token') == 'fresh-access-private'
        assert datetime.datetime.fromisoformat(stored('expired', 'oauth_expires_at').replace('Z', '+00:00')) > datetime.datetime.now(datetime.timezone.utc)
        run('request', base + '/echo', '--auth', 'expired')
        assert len(state['tokens']) == 1
        oauth('body', style='body')
        state['reply'] = {'access_token': 'fresh-access-private', 'refresh_token': 'rotated-private', 'scope': 'read'}
        run('request', base + '/echo', '--auth', 'body')
        fields = urllib.parse.parse_qs(state['tokens'][0]['body'])
        assert fields['client_secret'] == ['client-private'] and fields['client_id'] == ['test-client']
        assert 'Authorization' not in state['tokens'][0]['headers']
        assert stored('body', 'oauth_refresh_token') == 'rotated-private'
        assert stored('body', 'oauth_expires_at') is None and stored('body', 'oauth_scope') == 'read'
        oauth('revoked')
        state['reply'] = {'error': 'invalid_grant', 'error_description': 'client-private refresh-private'}
        state['token_status'] = 400
        revoked = run('request', base, '--auth', 'revoked', code=3)
        assert revoked['code'] == 'RECONNECT' and 'oauth authorize revoked' in revoked['message']
        assert stored('revoked', 'oauth_access_token') == 'old-access-private'
        oauth('no-refresh', refresh=False)
        assert run('request', base, '--auth', 'no-refresh', code=3)['code'] == 'RECONNECT'
        assert not state['tokens']
        oauth('bad-server')
        state['reply'] = {'error': 'server_error', 'error_description': 'client-private'}
        state['token_status'] = 500
        assert run('request', base, '--auth', 'bad-server', code=3)['code'] == 'OAUTH_REFRESH'
        assert stored('bad-server', 'oauth_access_token') == 'old-access-private'
        assert run('request', base + '/large', code=3)['code'] == 'BODY_TOO_LARGE'
        assert run('request', base + '/slow-body', '--timeout', '500', code=3)['code'] == 'TIMEOUT'
        with socket.socket() as closed:
            closed.bind(('127.0.0.1', 0))
            port = closed.getsockname()[1]
        assert run('request', f'http://127.0.0.1:{port}', '--timeout', '1000', code=3)['code'] == 'NETWORK'
        print(f'PASS {checks} HTTP checks: envelopes, echo, auth precedence, OAuth refresh, redaction, bounds, timeout, redirects and no retry')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
