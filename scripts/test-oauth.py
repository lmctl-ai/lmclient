#!/usr/bin/env python3
"""Offline JVM/native OAuth tests using the vendored strict Node mock IdP (scripts/mock-idp.js) as oracle."""
import contextlib
import json
import os
import re
from pathlib import Path
import queue
import shutil
import socket
import sqlite3
import subprocess
import sys
from jvm_noise import java_command, strip_jvm_noise
from temp_cleanup import temporary_directory
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar'
COMMAND = java_command(artifact)
# The strict mock IdP is vendored in-repo (canonical copy: lmconn scripts/mock-idp.js); LMCONN_MOCK_IDP overrides it.
MOCK = Path(os.environ.get('LMCONN_MOCK_IDP', str(ROOT / 'scripts/mock-idp.js')))
SECRET = 'dummy-oauth-client-secret'
checks = 0
outputs = []

# The standalone mock has no fault-selection flags or log output. This child imports
# its pinned factory and exposes only endpoints and its redacted request log on stdout.
# The optional token proxy mutates responses; it does not implement OAuth grants.
NODE = r'''
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:http';
import { createInterface } from 'node:readline';
const { createMockIdP } = await import(pathToFileURL(process.argv[2]).href);
const settings = JSON.parse(process.argv[3]);
const idp = await createMockIdP({port:0, requirePkce:!settings.noPkce,
  misbehave:settings.mode, formEncodedTokenResponse:settings.form, rotateRefreshTokens:settings.rotate});
idp.registerClient({clientId:'mock-client', clientSecret:'dummy-oauth-client-secret',
  redirectUris:[settings.redirect], authStyle:settings.style || 'header'});
let proxy;
let tokenUrl = idp.tokenUrl;
if (['omit-refresh', 'missing-expiry', 'extra', '500', 'stall'].includes(settings.mode)) {
  proxy = createServer(async (req, res) => {
    const chunks=[]; for await (const chunk of req) chunks.push(chunk);
    if (settings.mode === 'stall') return;
    const upstream = await fetch(idp.tokenUrl, {method:'POST',body:Buffer.concat(chunks),headers:{authorization:req.headers.authorization || '', 'content-type':'application/x-www-form-urlencoded'}});
    const token = await upstream.json();
    if (settings.mode === 'omit-refresh' && new URLSearchParams(Buffer.concat(chunks).toString()).get('grant_type') === 'refresh_token') delete token.refresh_token;
    if (settings.mode === 'missing-expiry') delete token.expires_in;
    if (settings.mode === 'extra') token.extra = {nested:[true,null,'escaped "text"']};
    if (settings.mode === '500') { res.writeHead(500); res.end(JSON.stringify({error:'server_error',error_description:'dummy-oauth-client-secret'})); return; }
    res.writeHead(upstream.status, {'content-type':'application/json'}); res.end(JSON.stringify(token));
  });
  await new Promise(resolve => proxy.listen(0,'127.0.0.1',resolve));
  tokenUrl = `http://127.0.0.1:${proxy.address().port}/token`;
}
console.log(JSON.stringify({authUrl:idp.authUrl,tokenUrl,userinfoUrl:idp.userinfoUrl}));
const reader=createInterface({input:process.stdin});
for await (const line of reader) {
  if (line === 'log') console.log(JSON.stringify({events:idp.log}));
  if (line === 'close') break;
}
if (proxy) { proxy.closeAllConnections(); await new Promise(resolve => proxy.close(resolve)); }
await idp.close();
'''

with temporary_directory(prefix='lmclient-oauth-') as directory:
    db = Path(directory) / 'creds.db'
    env = {**os.environ, 'LMCLIENT_DB': str(db)}

    def get(service, field):
        if not db.exists(): return None
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            try: row = conn.execute('SELECT value FROM creds WHERE service=? AND field=?', (service, field)).fetchone()
            except sqlite3.OperationalError: return None
            return row[0] if row else None

    def put(service, field, value):
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO creds VALUES (?,?,?,datetime('now'))", (service, field, value))

    def redacted(text):
        secrets = [SECRET, 'revoked-refresh-secret']
        if db.exists():
            with contextlib.closing(sqlite3.connect(db)) as conn, conn:
                secrets += [r[0] for r in conn.execute("SELECT value FROM creds WHERE field IN ('oauth_access_token','oauth_refresh_token','oauth_client_secret')") if r[0]]
        assert all(s not in text for s in secrets), 'lmclient output disclosed a secret'

    def check(p, expected=0, error=None):
        global checks
        redacted(p.stdout + p.stderr)
        outputs.append(p.stdout + p.stderr)
        assert p.returncode == expected, f'expected exit {expected}, got {p.returncode}: {p.stdout}'
        assert len(p.stdout.strip().splitlines()) == 1, 'expected one JSON envelope'
        data = json.loads(p.stdout)
        assert data['ok'] == (expected == 0)
        if error: assert data['error']['code'] == error, data
        checks += 1
        return data.get('result', data.get('error'))

    def run(*args, expected=0, error=None, stdin=None):
        return check(subprocess.run(COMMAND + ['oauth', *args], env=env, input=stdin,
                                    capture_output=True, text=True, timeout=20), expected, error)

    for args in [[], ['other', 'x'], ['status'], ['status', 'x', '--manual'],
                 ['authorize', 'x', '--wat'], ['authorize', 'x', '--port', '65536'],
                 ['authorize', 'x', '--timeout', '0'], ['authorize', 'x', '--manual', '--auto-follow'],
                 ['authorize', 'x', '--scope', 'one', '--scope', 'two']]:
        run(*args, expected=2, error='USAGE')
    missing = run('authorize', 'unconfigured', expected=3, error='MISSING_CONFIG')
    assert 'oauth_client_id' in missing['message'] and 'presets' in missing['message']
    status = run('status', 'absent', '--json')
    assert status == {'service':'absent','authorized':False,'expiresAt':None,'expired':False,
                      'hasRefreshToken':False,'scope':'','tokenUrl':None}

    if not MOCK.exists():
        raise SystemExit(f'oauth: mock IdP missing: {MOCK} (vendored at scripts/mock-idp.js; LMCONN_MOCK_IDP overrides)')
    if not shutil.which('node'):
        print(f'oauth: {checks} offline checks passed; SKIPPED cross-language checks (node is not on PATH)')
        sys.exit(0)

    @contextlib.contextmanager
    def fixture(**settings):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
        settings['redirect'] = f'http://127.0.0.1:{port}/callback'
        wrapper = Path(directory) / 'oracle.mjs'
        wrapper.write_text(NODE)
        child = subprocess.Popen(['node', str(wrapper), str(MOCK), json.dumps(settings)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        lines = queue.Queue()
        def pump():
            for line in child.stdout: lines.put(line)
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            urls = json.loads(lines.get(timeout=10))
            def logs():
                child.stdin.write('log\n'); child.stdin.flush()
                text = lines.get(timeout=5); redacted(text)
                return json.loads(text)['events']
            yield urls, port, logs
        finally:
            try:
                if child.poll() is None:
                    try:
                        child.stdin.write('close\n'); child.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait()
                reader.join(timeout=5)
                assert not reader.is_alive(), 'mock IdP output reader did not stop'
                redacted(child.stderr.read())
            finally:
                if child.poll() is None:
                    child.kill(); child.wait()
                child.stdin.close(); child.stdout.close(); child.stderr.close()

    def configure(service, urls):
        # Dummy credentials enter the shared store, never the Java process argv.
        put(service, 'oauth_client_id', 'mock-client')
        put(service, 'oauth_client_secret', SECRET)
        put(service, 'oauth_auth_url', urls['authUrl'])
        put(service, 'oauth_token_url', urls['tokenUrl'])

    def authorize(service, urls, port, *extra, expected=0, error=None):
        configure(service, urls)
        return run('authorize', service, '--port', str(port), '--timeout', '6000', '--auto-follow', *extra, expected=expected, error=error)

    def protected(service, urls):
        request = urllib.request.Request(urls['userinfoUrl'], headers={'Authorization': 'Bearer ' + get(service, 'oauth_access_token')})
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.load(response)
            assert body == {'sub':'mock-user-1', 'client_id':'mock-client', 'scope':'read write'}

    with fixture(rotate=True) as (urls, port, logs):
        result = authorize('happy', urls, port, '--scope', 'read write', '--auth-query', 'state=ignored&client_secret=hidden&access_type=offline')
        assert set(result) == {'service','expiresAt','hasRefreshToken','scope'}
        assert result['hasRefreshToken'] and result['scope'] == 'read write'
        events = logs()
        assert [e['path'] for e in events] == ['/authorize','/token'], events
        params = events[0]['params']
        assert params['code_challenge_method'] == 'S256' and len(params['code_challenge']) == 43
        assert params['state'] != 'ignored' and 'client_secret' not in params
        assert events[1]['authStyle'] == 'header'
        status = run('status', 'happy'); assert status['authorized'] and not status['expired']
        protected('happy', urls)
        old = get('happy', 'oauth_refresh_token')
        put('happy', 'oauth_expires_at', '1970-01-01T00:00:00Z')
        assert run('status', 'happy')['expired']
        run('refresh', 'happy')
        assert get('happy', 'oauth_refresh_token') != old
        assert not run('status', 'happy')['expired']
        protected('happy', urls)
        put('happy', 'oauth_refresh_token', 'revoked-refresh-secret')
        run('refresh', 'happy', expected=3, error='RECONNECT')
        assert get('happy', 'oauth_refresh_token') == 'revoked-refresh-secret'

    for mode in ['bad-state', 'bad-json', '500']:
        with fixture(mode=mode) as (urls, port, logs):
            authorize(mode, urls, port, expected=3, error='OAUTH_ERROR')
            assert not run('status', mode)['authorized']
            paths = [e['path'] for e in logs()]
            assert paths.count('/authorize') == 1 and paths.count('/token') == (0 if mode == 'bad-state' else 1)

    for mode in ['string-expires', 'missing-expiry', 'extra', 'omit-refresh']:
        with fixture(mode=mode) as (urls, port, logs):
            result = authorize(mode, urls, port)
            assert result['scope'] == ''
            assert result['expiresAt'] is None if mode == 'missing-expiry' else result['expiresAt'] is not None
            if mode == 'missing-expiry': assert run('status', mode)['expiresAt'] is None
            if mode == 'omit-refresh':
                old = get(mode, 'oauth_refresh_token'); run('refresh', mode)
                assert get(mode, 'oauth_refresh_token') == old

    with fixture(form=True, style='body') as (urls, port, logs):
        result = authorize('body', urls, port, '--auth-style', 'body', '--scope', 'read write')
        assert result['scope'] == 'read write' and logs()[1]['authStyle'] == 'body'
        protected('body', urls)

    with fixture(noPkce=True) as (urls, port, logs):
        authorize('legacy', urls, port, '--no-pkce')
        assert 'code_challenge' not in logs()[0]['params']

    with fixture() as (urls, port, logs):
        configure('timeout', urls)
        run('authorize', 'timeout', '--port', str(port), '--timeout', '150', expected=3, error='TIMEOUT')
        assert not logs()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port)) # callback server really closed
        # A preset supplies GitHub's missing auth URL, while flags override its token endpoint.
        put('github','oauth_client_id','mock-client')
        result = run('authorize','github','--token-url',urls['tokenUrl'],'--timeout','150', expected=3,error='TIMEOUT')
        assert 'https://github.com/login/oauth/authorize' in outputs[-1]

    with fixture(mode='stall') as (urls, port, logs):
        configure('stall', urls)
        run('authorize','stall','--port',str(port),'--timeout','500','--auto-follow',expected=3,error='TIMEOUT')

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args): return None

    with fixture(form=True, style='body') as (urls, port, logs):
        configure('manual', urls)
        child = subprocess.Popen(COMMAND + ['oauth','authorize','manual','--manual','--port',str(port),
                                 '--auth-style','body','--timeout','6000'], env=env,
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            # The JVM may write warnings (for example JDK 24+ native-access notices while the SQLite
            # driver loads) to stderr before the authorize URL, so scan lines for the URL instead of
            # trusting the first line; everything consumed is kept for the redaction/envelope checks.
            consumed, url, deadline = [], None, time.monotonic() + 15
            while url is None:
                assert time.monotonic() < deadline, 'authorize URL not printed within 15 s: ' + ''.join(consumed)
                line = child.stderr.readline()
                assert line, 'lmclient exited before printing the authorize URL: ' + ''.join(consumed)
                consumed.append(line)
                found = re.search(r'https?://\S+', line)
                if found and '/authorize?' in found.group(0): url = found.group(0)
            line = ''.join(consumed)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            assert query.get('client_id') == ['mock-client'] and query.get('state') and query.get('redirect_uri'), url
            try: urllib.request.build_opener(NoRedirect).open(url,timeout=5)
            except urllib.error.HTTPError as redirect:
                assert redirect.code == 302
                location = redirect.headers['Location']
            stdout,stderr = child.communicate(location+'\n',timeout=10)
            code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)['code'][0]
            assert code not in stdout+stderr+line
            check(subprocess.CompletedProcess([],child.returncode,stdout,line+stderr))
            assert [e['path'] for e in logs()] == ['/authorize','/token']
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate()  # Reap and close all pipes, including early assertion failures.
    for output in outputs: redacted(output)
    print(f'oauth: {checks} checks passed; shared Node IdP verified PKCE, manual/body/form, refresh, protected userinfo, and adversarial errors')
