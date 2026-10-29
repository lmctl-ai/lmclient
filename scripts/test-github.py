#!/usr/bin/env python3
"""Offline checks for the github area against a loopback fixture API, plus an opt-in live check.
Run: python3 scripts/test-github.py target/lmclient-0.2.0-all.jar   (also accepts a native executable)
Set LMCLIENT_GITHUB_LIVE=1 to also hit api.github.com (repos lmctl-ai, and user when a token resolves).
Token sources are exercised with dummy values: a seeded SQLite store, GITHUB_TOKEN/GH_TOKEN, a fake `gh`
on PATH. The fixture records whether an Authorization header was present, never its value.
"""
import http.server
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar').resolve()
COMMAND = ['java', '-jar', str(artifact)] if artifact.suffix == '.jar' else [str(artifact)]
SECRETS = ['store-token-private', 'env-token-private', 'gh-token-private']
state = {'requests': []}
checks = 0

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def respond(self, status, body, headers=None):
        raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        auth = self.headers.get('Authorization')
        state['requests'].append({'path': self.path, 'authorized': auth is not None,
                                  'bearer': bool(auth and auth.startswith('Bearer ')),
                                  'accept': self.headers.get('Accept'), 'agent': self.headers.get('User-Agent')})
        origin = f'http://{self.headers["Host"]}'
        if self.path == '/user':
            if not auth or auth.removeprefix('Bearer ') not in SECRETS: return self.respond(401, {'message': 'Bad credentials'})
            return self.respond(200, {'login': 'octo', 'name': 'Octo Cat', 'id': 583231, 'public_repos': 8})
        if self.path == '/orgs/acme/repos?per_page=30&sort=full_name':
            return self.respond(200, [{'name': 'a', 'description': 'first', 'stargazers_count': 5},
                                      {'name': 'b', 'description': None, 'stargazers_count': 0}])
        if self.path == '/orgs/paged/repos?per_page=3&sort=full_name':
            return self.respond(200, [{'name': 'r1', 'stargazers_count': 1}, {'name': 'r2', 'stargazers_count': 2}],
                                {'Link': f'<{origin}/orgs/paged/repos?per_page=3&sort=full_name&page=2>; rel="next"'})
        if self.path == '/orgs/paged/repos?per_page=3&sort=full_name&page=2':
            return self.respond(200, [{'name': 'r3', 'stargazers_count': 3}, {'name': 'r4', 'stargazers_count': 4}])
        if self.path.startswith('/orgs/mike/repos'):
            return self.respond(404, {'message': 'Not Found'})
        if self.path == '/users/mike/repos?per_page=30&sort=full_name':
            return self.respond(200, [{'name': 'personal', 'description': 'd', 'stargazers_count': 2}])
        if self.path.startswith('/orgs/forbidden/'):
            return self.respond(403, {'message': 'API rate limit exceeded'})
        if self.path.startswith('/orgs/broken/'):
            return self.respond(500, b'oops')
        if self.path.startswith('/orgs/weird/'):
            return self.respond(200, {'not': 'a list'})
        return self.respond(404, {'message': 'Not Found'})

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
API = f'http://127.0.0.1:{server.server_address[1]}'

tmp = tempfile.TemporaryDirectory(prefix='lmclient-github-test-')
empty_db = Path(tmp.name) / 'empty.db'
seeded_db = Path(tmp.name) / 'seeded.db'
conn = sqlite3.connect(seeded_db)
conn.execute('CREATE TABLE IF NOT EXISTS creds (service TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (service, field))')
conn.execute("INSERT INTO creds VALUES ('github','api_key',?,'2026-10-29T00:00:00Z')", (SECRETS[0],))
conn.commit(); conn.close()
# PATH without the real gh (so the fallback is deterministic), plus a dir with a fake gh.
nogh = Path(tmp.name) / 'nogh'; nogh.mkdir()
fakegh = Path(tmp.name) / 'fakegh'; fakegh.mkdir()
for tool in ('java', 'sh'):
    real = subprocess.run(['which', tool], capture_output=True, text=True).stdout.strip()
    if real:
        os.symlink(real, nogh / tool); os.symlink(real, fakegh / tool)
gh = fakegh / 'gh'
gh.write_text('#!/bin/sh\n[ "$1" = auth ] && [ "$2" = token ] && printf "%s\\n" "' + SECRETS[2] + '"\n')
gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

def env(db=empty_db, path=nogh, **extra):
    base = {k: v for k, v in os.environ.items() if k not in ('GITHUB_TOKEN', 'GH_TOKEN', 'LMCLIENT_DB', 'LMCONN_DB', 'LMCLIENT_GITHUB_API')}
    base.update({'LMCLIENT_DB': str(db), 'LMCLIENT_GITHUB_API': API, 'PATH': str(path)})
    if 'JAVA_HOME' in os.environ: base['JAVA_HOME'] = os.environ['JAVA_HOME']
    base.update(extra)
    return base

def run(*args, code=0, env=None):
    global checks
    process = subprocess.run(COMMAND + ['github', *args], text=True, encoding='utf-8', capture_output=True, timeout=120, env=env)
    assert process.returncode == code, (args, process.returncode, process.stdout, process.stderr)
    lines = [l for l in process.stdout.splitlines() if l.strip()]
    assert len(lines) == 1, ('one JSON line', process.stdout)
    envelope = json.loads(lines[0])
    assert envelope['ok'] is (code == 0), envelope
    for secret in SECRETS:
        assert secret not in process.stdout + process.stderr, ('secret leaked', args)
    checks += 1
    return envelope, process

def error(*args, code, expect, env=None):
    envelope, process = run(*args, code=code, env=env)
    assert envelope['error']['code'] == expect, (expect, envelope)
    assert envelope['error']['message'], envelope
    return envelope, process

# usage
for args in ((), ('orgs',), ('user', 'extra'), ('repos',), ('repos', 'a', '--limit'), ('repos', 'a', '--limit', '0'),
             ('repos', 'a', '--limit', '5000'), ('repos', 'a', '--limit', 'x'), ('repos', 'a', 'b'), ('repos', 'a', '--bogus')):
    error(*args, code=2, expect='USAGE', env=env())
assert not state['requests'], 'usage errors must not call the API'

# anonymous repos: lmconn field names plus repos summaries; Accept and User-Agent headers
envelope, process = run('repos', 'acme', env=env())
r = envelope['result']
assert r['org'] == 'acme' and r['count'] == 2 and r['names'] == ['a', 'b'], r
assert r['repos'] == [{'name': 'a', 'description': 'first', 'stars': 5}, {'name': 'b', 'description': None, 'stars': 0}], r
assert r['auth'] == 'anonymous' and r['tokenSource'] == 'anonymous', r
assert process.stderr.strip() == '', process.stderr
last = state['requests'][-1]
assert last['authorized'] is False and last['accept'] == 'application/vnd.github+json' and last['agent'] == 'lmclient', last

# pagination to --limit and user-endpoint fallback on 404
envelope, _ = run('repos', 'paged', '--limit', '3', env=env())
assert envelope['result']['names'] == ['r1', 'r2', 'r3'] and envelope['result']['count'] == 3, envelope
assert [q['stars'] for q in envelope['result']['repos']] == [1, 2, 3], envelope
envelope, _ = run('repos', 'mike', env=env())
assert envelope['result']['names'] == ['personal'], envelope
assert [q['path'] for q in state['requests'][-2:]] == ['/orgs/mike/repos?per_page=30&sort=full_name', '/users/mike/repos?per_page=30&sort=full_name']

# token sources: store > env > gh > anonymous; header present, value never printed
envelope, _ = run('user', env=env(db=seeded_db, GITHUB_TOKEN=SECRETS[1]))
assert envelope['result'] == {'login': 'octo', 'name': 'Octo Cat', 'id': 583231, 'publicRepos': 8, 'auth': 'store', 'tokenSource': 'store'}, envelope
assert state['requests'][-1]['bearer'] is True
envelope, _ = run('user', env=env(GH_TOKEN=SECRETS[1]))
assert envelope['result']['auth'] == 'env:GH_TOKEN', envelope
envelope, _ = run('user', env=env(path=fakegh))
assert envelope['result']['auth'] == 'gh' and state['requests'][-1]['bearer'] is True, envelope
envelope, _ = run('repos', 'acme', env=env(path=fakegh))
assert envelope['result']['auth'] == 'gh', envelope

# errors
error('user', code=3, expect='MISSING_KEY', env=env())                          # anonymous user: no API call
assert state['requests'][-1]['path'] != '/user' or state['requests'][-1]['authorized']
envelope, _ = error('user', code=3, expect='AUTH', env=env(GITHUB_TOKEN='x-not-a-real-token-x'))
assert 'Bad credentials' in envelope['error']['message'] and 'auth: env:GITHUB_TOKEN' in envelope['error']['message'], envelope
envelope, _ = error('repos', 'forbidden', code=3, expect='AUTH', env=env())
assert 'auth: anonymous' in envelope['error']['message'], envelope
error('repos', 'nobody', code=3, expect='NOT_FOUND', env=env())
error('repos', 'broken', code=3, expect='HTTP', env=env())
error('repos', 'weird', code=3, expect='INVALID_RESPONSE', env=env())
server.shutdown(); server.server_close()
error('repos', 'acme', code=3, expect='NETWORK', env=env())                       # fixture gone: connection refused

if os.environ.get('LMCLIENT_GITHUB_LIVE') == '1':
    live = {k: v for k, v in os.environ.items() if k not in ('LMCLIENT_GITHUB_API',)}
    envelope, _ = run('repos', 'lmctl-ai', '--limit', '3', env=live)
    assert envelope['result']['count'] == 3 and len(envelope['result']['repos']) == 3, envelope
    if envelope['result']['auth'] != 'anonymous':
        envelope, _ = run('user', env=live)
        assert envelope['result']['login'], envelope
    mode = 'live api.github.com included'
else:
    mode = 'offline; set LMCLIENT_GITHUB_LIVE=1 for api.github.com'
tmp.cleanup()
print(f"lmclient github checks: {checks} passed ({'native' if artifact.suffix != '.jar' else 'JVM'}; {mode})")
