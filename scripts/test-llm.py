#!/usr/bin/env python3
"""Offline API and executable-argv fixtures; optional live chats.
Run: python3 scripts/test-llm.py target/lmclient-0.2.0-all.jar
Opt-in: LMCLIENT_TEST_LLM_LIVE=1 (all providers), or a comma-separated provider list.
No external API/CLI is called unless that variable is set. Dummy secrets only.
"""
import http.server
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
artifact = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'target/lmclient-0.2.0-all.jar').resolve()
COMMAND = [shutil.which('java') or 'java', '-jar', str(artifact)] if artifact.suffix == '.jar' else [str(artifact)]
state = {'mode': 'ok', 'requests': []}
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        request = {'path': self.path, 'auth': self.headers.get('Authorization'),
                   'body': json.loads(self.rfile.read(int(self.headers['Content-Length'])))}
        state['requests'].append(request)
        mode = state['mode']
        if mode == 'slow': time.sleep(2)
        if mode == 'unauthorized':
            status, payload = 401, 'denied fixture-api-private Bearer unrelated-private-token'
        elif mode == 'retry' and len(state['requests']) == 1 or mode == 'rate':
            status, payload = 429, 'rate limited'
        elif mode == 'invalid':
            status, payload = 200, '{broken'
        else:
            status = 200
            payload = json.dumps({'model': 'fixture-model', 'choices': [{'message': {'content': 'fixture-api-private' if mode == 'echo' else 'pong'}}], 'usage': {'total_tokens': 4}})
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try: self.wfile.write(payload.encode())
        except (BrokenPipeError, ConnectionResetError): pass

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
checks = 0
live_option = os.environ.get('LMCLIENT_TEST_LLM_LIVE', '')
try:
    with tempfile.TemporaryDirectory(prefix='lmclient-llm-') as directory:
        root = Path(directory)
        db = root / 'creds.db'
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE creds(service TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(service,field))')
        env = {**os.environ, 'LMCLIENT_DB': str(db), 'DEEPSEEK_API_KEY': 'fixture-api-private',
               'LMCLIENT_LLM_DEEPSEEK_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1',
               'PATH': str(root) + os.pathsep + os.environ['PATH'], 'CLI_FIXTURE_RECORD': str(root / 'argv.json'),
               'CLI_FIXTURE_MODE': 'ok'}
        # Fixtures never inherit real provider keys or accidentally use real endpoints.
        for name in ['OPENROUTER_API_KEY', 'OLLAMA_API_KEY']:
            env.pop(name, None)
        for name in ['OPENROUTER', 'OLLAMA_CLOUD']:
            env['LMCLIENT_LLM_' + name + '_BASE_URL'] = f'http://127.0.0.1:{server.server_port}/v1'
        fixture = '''import json, os, sys, time
from pathlib import Path
Path(os.environ['CLI_FIXTURE_RECORD']).write_text(json.dumps({'argv':sys.argv[1:], 'cwd':os.getcwd()}))
mode=os.environ.get('CLI_FIXTURE_MODE','ok')
if mode=='slow':
 Path(os.environ['CLI_FIXTURE_RECORD']+'.pid').write_text(str(os.getpid()))
 time.sleep(30)
if mode=='error':
 print('Bearer unrelated-private-token '+os.environ.get('DEEPSEEK_API_KEY','')+' '+'x'*700,file=sys.stderr)
 sys.exit(7)
if mode=='huge':
 print('x'*(2*1024*1024+1))
else: print('  pong  ')
'''
        if os.name != 'nt':
            for name in ['claude', 'codex', 'agy', 'kimi']:
                path = root / name
                path.write_text('#!' + sys.executable + '\n' + fixture)
                path.chmod(0o755)
        def run(*args, code=0, input=None, extra_env=None):
            global checks
            p = subprocess.run(COMMAND + ['llm'] + list(args), capture_output=True, text=True, encoding='utf-8',
                               input=input, timeout=30, env={**env, **(extra_env or {})})
            assert p.returncode == code, f'check {checks+1}: unexpected exit {p.returncode}; {p.stdout}'
            assert len(p.stdout.splitlines()) == 1, 'one envelope required'
            for secret in ['fixture-api-private', 'fixture-store-private', 'unrelated-private-token']:
                assert secret not in p.stdout + p.stderr, 'secret leaked'
            data = json.loads(p.stdout)
            assert data['ok'] == (code == 0)
            checks += 1
            return data['result'] if code == 0 else data['error']
        for args in [[], ['chat'], ['chat','unknown'], ['providers','extra'], ['chat','deepseek','--max-tokens','0'],
                     ['chat','deepseek','--timeout','0'], ['chat','deepseek','--prompt'],
                     ['chat','deepseek','--prompt','x','--stdin'], ['chat','deepseek','--prompt','x','--prompt','y'], ['probe','unknown']]:
            assert run(*args, code=2)['code'] == 'USAGE'
        providers = run('providers')
        assert [p['name'] for p in providers] == ['deepseek','openrouter','ollama-cloud','claude','codex','agy','kimi']
        assert providers[0]['key'] == 'env:DEEPSEEK_API_KEY' and providers[1]['key'] == 'missing'
        assert providers[-1]['key'] == 'none'
        result = run('chat','deepseek','--prompt','ping','--system','be brief','--model','override','--max-tokens','12')
        assert result['text'] == 'pong' and result['provider'] == 'deepseek' and result['model'] == 'fixture-model'
        assert result['usage'] == {'total_tokens':4} and result['keySource'] == 'env:DEEPSEEK_API_KEY'
        assert state['requests'][-1] == {'path':'/v1/chat/completions','auth':'Bearer fixture-api-private',
                                        'body':{'model':'override','max_tokens':12,'messages':[{'role':'system','content':'be brief'},{'role':'user','content':'ping'}]}}
        with sqlite3.connect(db) as connection:
            connection.execute('INSERT INTO creds VALUES(?,?,?,?)',('deepseek','api_key','fixture-store-private','now'))
        assert run('chat','deepseek','--prompt','ping')['keySource'] == 'store'
        assert state['requests'][-1]['auth'] == 'Bearer fixture-store-private'
        with sqlite3.connect(db) as connection: connection.execute('DELETE FROM creds')
        prompt_file = root / 'prompt.txt'
        prompt_file.write_text('file héllo',encoding='utf-8')
        run('chat','deepseek','--prompt-file',str(prompt_file))
        assert state['requests'][-1]['body']['messages'][0]['content'] == 'file héllo'
        run('chat','deepseek',input='stdin 世界')
        assert state['requests'][-1]['body']['messages'][0]['content'] == 'stdin 世界'
        state['mode'] = 'echo'
        assert run('chat','deepseek','--prompt','ping')['text'] == '[REDACTED]'
        state['mode'] = 'unauthorized'
        assert run('chat','deepseek','--prompt','ping',code=3)['code'] == 'HTTP_ERROR'
        state['mode'] = 'invalid'
        assert run('chat','deepseek','--prompt','ping',code=3)['code'] == 'API_ERROR'
        state['mode'] = 'retry'; state['requests'].clear()
        start = time.monotonic()
        assert run('chat','deepseek','--prompt','ping')['text'] == 'pong'
        assert len(state['requests']) == 2 and time.monotonic()-start >= 3
        state['mode'] = 'rate'; state['requests'].clear()
        assert run('chat','deepseek','--prompt','ping',code=3)['code'] == 'HTTP_ERROR'
        assert len(state['requests']) == 2, 'must retry exactly once'
        state['mode'] = 'slow'
        assert run('chat','deepseek','--prompt','ping','--timeout','500',code=3)['code'] == 'TIMEOUT'
        state['mode'] = 'ok'
        assert run('chat','openrouter','--prompt','ping',code=3)['code'] == 'MISSING_KEY'
        if os.name == 'nt':
            print('SKIPPED CLI executable fixtures on Windows (POSIX shebang fixture); API tests ran')
        else:
            prompt = 'hello; $(echo BAD) " quoted'
            commands = {'claude':['-p'],'codex':['exec','--skip-git-repo-check'],'agy':['-p'],'kimi':['-p']}
            for name, prefix in commands.items():
                result = run('chat',name,'--system','be brief','--prompt',prompt)
                assert result['text'] == 'pong' and result['model'] is None and result['keySource'] == 'none'
                record = json.loads((root/'argv.json').read_text())
                assert record['argv'] == prefix+['be brief\n\n'+prompt]
                # macOS /var and /private/var name the same temporary directory.
                assert os.path.realpath(record['cwd']) == os.path.realpath(tempfile.gettempdir())
            error = run('chat','claude','--prompt','x',code=3,extra_env={'CLI_FIXTURE_MODE':'error'})
            assert error['code'] == 'CLI_ERROR' and len(error['message'].split(': ',1)[1]) <= 500
            assert run('chat','claude','--prompt','x','--timeout','1000',code=3,extra_env={'CLI_FIXTURE_MODE':'slow'})['code'] == 'TIMEOUT'
            pid = int((root/'argv.json.pid').read_text())
            time.sleep(.1)
            try: os.kill(pid,0)
            except ProcessLookupError: pass
            else: raise AssertionError('timed-out child still alive')
            assert run('chat','claude','--prompt','x',code=3,extra_env={'CLI_FIXTURE_MODE':'huge'})['code'] == 'OUTPUT_TOO_LARGE'
            (root/'claude').unlink()
            assert run('chat','claude','--prompt','x',code=3,extra_env={'PATH':str(root)})['code'] == 'CLI_ERROR'
            rows = run('probe','openrouter','codex','deepseek')
            assert [row['ok'] for row in rows] == [False,True,True]
            assert rows[0]['kind'] == 'api' and rows[1]['kind'] == 'cli'
            assert rows[1]['reply'] == 'pong'
        print(f'PASS {checks} LLM fixture checks: API, argv, timeouts, retry, source precedence, redaction and probe continuation')
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=5)

if live_option:
    names = ['deepseek','openrouter','ollama-cloud','claude','codex','agy','kimi'] if live_option == '1' else live_option.split(',')
    failures = []
    with tempfile.TemporaryDirectory(prefix='lmclient-llm-live-') as directory:
        live_env = {k:v for k,v in os.environ.items() if not (k.startswith('LMCLIENT_LLM_') and k.endswith('_BASE_URL'))}
        live_env['LMCLIENT_DB'] = str(Path(directory)/'creds.db')
        for name in names:
            if name not in ['deepseek','openrouter','ollama-cloud','claude','codex','agy','kimi']:
                raise SystemExit('invalid live provider selection')
            p = subprocess.run(COMMAND+['llm','chat',name,'--prompt','Reply with exactly: pong','--timeout','120000'],
                               capture_output=True,text=True,encoding='utf-8',timeout=140,env=live_env)
            value = json.loads(p.stdout)
            # Never echo raw provider output or child stderr from the live test runner.
            if p.returncode == 0 and value.get('ok') and value['result'].get('text','').strip():
                print('PASS live '+name+' (nonempty reply, latencyMs='+str(value['result']['latencyMs'])+')')
            else:
                failures.append(name)
                print('FAIL live '+name+' ('+value.get('error',{}).get('code','invalid-envelope')+')')
    if failures: raise SystemExit(1)
