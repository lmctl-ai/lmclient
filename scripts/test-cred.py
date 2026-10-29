#!/usr/bin/env python3
"""Offline credential CLI checks and bidirectional Java/Node SQLite interoperability."""
from datetime import datetime
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
from jvm_noise import java_command, strip_jvm_noise
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text().strip()
TARGET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / f'target/lmclient-{VERSION}-all.jar'
COMMAND = java_command(TARGET)
BASE_ENV = {k: v for k, v in os.environ.items() if not k.startswith(('LMCLIENT_', 'LMDB_', 'LMCONN_'))}
SECRET = 'dummy-credential-DO-NOT-LOG'
SECRETS = [SECRET, 'dummy-java-to-node', 'dummy-node-to-java', 'dummy-path-secret']
checks = 0


def redact(text, values):
    # Cover raw output and JSON-escaped values without logging argv or stdin.
    variants = set()
    for value in values:
        if value:
            variants.add(value)
            variants.add(json.dumps(value, ensure_ascii=True)[1:-1])
            variants.add(json.dumps(value, ensure_ascii=False)[1:-1])
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, '<redacted>')
    return text


# Diagnostics must remain useful even if a failing process echoes its input.
_probe = 'dummy-quote"\\line\n世界'
assert redact(_probe + json.dumps(_probe), [_probe]) == '<redacted>"<redacted>"'

with tempfile.TemporaryDirectory(prefix='lmclient-cred-') as directory:
    database = str(Path(directory) / 'creds.db')
    environment = {**BASE_ENV, 'LMCLIENT_DB': database}

    def run(*args, code=0, error=None, stdin=None, env=None):
        global checks
        # Binary pipes avoid Python translating every LF to CRLF on Windows.
        process = subprocess.run(COMMAND + ['cred', *args],
                                 input=None if stdin is None else stdin.encode('utf-8'),
                                 capture_output=True, timeout=30,
                                 env={**environment, **(env or {})})
        secrets = [*SECRETS, stdin, *(env or {}).values()]
        if '--value' in args:
            index = args.index('--value') + 1
            if index < len(args):
                secrets.append(args[index])
        if process.returncode != code:
            # Decode leniently only for diagnostics: launcher/OS errors may use
            # the Windows code page rather than the CLI's UTF-8 encoding.
            stdout = redact(process.stdout.decode('utf-8', errors='replace'), secrets)
            stderr = redact(process.stderr.decode('utf-8', errors='replace'), secrets)
            raise AssertionError(
                f'unexpected credential command exit (check {checks + 1}, '
                f'expected {code}, actual {process.returncode}); '
                f'stdout={stdout[:4000]!r}; stderr={stderr[:4000]!r}')
        process.stdout = process.stdout.decode('utf-8')
        process.stderr = process.stderr.decode('utf-8')
        assert len(process.stdout.strip().splitlines()) == 1, 'exactly one JSON envelope required'
        envelope = json.loads(process.stdout)
        assert envelope['ok'] is (code == 0)
        if error:
            assert envelope['error']['code'] == error
        for secret in SECRETS:
            assert secret not in process.stderr, 'secret in stderr'
            if not (code == 0 and args[0] == 'get' and '--reveal' in args):
                assert secret not in process.stdout, 'secret in stdout'
        checks += 1
        return envelope.get('result', envelope.get('error')), process.stderr

    path_result = run('path')[0]
    assert set(path_result) == {'path'}
    assert os.path.realpath(path_result['path']) == os.path.realpath(database)
    assert not Path(database).exists(), 'path must not open the database'
    assert run('list')[0] == []
    assert run('get', 'service', 'key')[0] == {'service': 'service', 'field': 'key', 'set': False}
    run('get', 'service', 'key', '--reveal', code=3, error='NOT_FOUND')
    result, warning = run('set', 'service', 'key', '--value', SECRET)
    assert result == {'service': 'service', 'field': 'key', 'stored': True}
    assert 'argv' in warning and 'visible' in warning
    assert run('get', 'service', 'key')[0] == {'service': 'service', 'field': 'key', 'set': True}
    assert run('get', 'service', 'key', '--reveal')[0] == {'service': 'service', 'field': 'key', 'set': True, 'value': SECRET}
    rows = run('list')[0]
    assert len(rows) == 1 and set(rows[0]) == {'service', 'field', 'updated_at'}
    datetime.fromisoformat(re.sub(r'(\.\d{6})\d+', r'\1', rows[0]['updated_at']).replace('Z', '+00:00'))

    for value in [SECRET + '\n', '']:
        result, warning = run('set', 'service', 'key', '--env', 'LMCLIENT_CRED_TEST_VALUE',
                              env={'LMCLIENT_CRED_TEST_VALUE': value})
        assert result['stored'] is True and 'argv' not in warning
        assert run('get', 'service', 'key', '--reveal')[0]['value'] == value
        assert run('get', 'service', 'key')[0]['set'] is True
    run('set', 'service', 'key', '--env', 'LMCLIENT_CRED_TEST_MISSING', code=2, error='USAGE')
    # Stdin strips one trailing LF/CRLF; embedded line endings and other whitespace survive.
    for value, expected in [
        (SECRET + '\n', SECRET), (SECRET + '\r\n', SECRET),
        (SECRET + '\n\n', SECRET + '\n'),
        (SECRET + '\r\n\r\n', SECRET + '\r\n'),
        (SECRET + '\r', SECRET + '\r'), ('\n', ''), ('\r\n', ''),
        (f'  {SECRET} 🔑\nsecond\r\nline\t\x00end\n', f'  {SECRET} 🔑\nsecond\r\nline\t\x00end'),
        ('', ''), (SECRET + 'x' * 131072, SECRET + 'x' * 131072),
    ]:
        run('set', 'service', 'key', '--stdin', stdin=value)
        assert run('get', 'service', 'key', '--reveal')[0]['value'] == expected
    for value in [SECRET + '\n', SECRET + '\r\n']:
        run('set', 'service', 'key', '--value', value)
        assert run('get', 'service', 'key', '--reveal')[0]['value'] == value
    assert len(run('list')[0]) == 1, 'updates must not insert duplicate rows'
    # Isolate argument transport from stdin: on Windows the launcher parses
    # quotes/backslashes and Unicode before CredArea ever receives the args.
    for name, field in [('plain-service', 'plain-field'),
                        ('quoted"service', 'field'),
                        ('backslash\\service', 'field'),
                        ('世界', 'field'), ('service', 'line\nfield')]:
        if sys.platform == 'win32' and ('\n' in name or '\n' in field):
            print('SKIP newline name/field case: newline in argv is not portable on Windows')
            continue
        run('set', name, field, '--stdin', stdin=SECRET)
        assert run('get', name, field, '--reveal')[0] == {
            'service': name, 'field': field, 'set': True, 'value': SECRET}
        assert run('delete', name, field)[0] == {'deleted': True}
    name = 'quoted"service\\世界'
    field = 'line\nfield'
    if sys.platform == 'win32':
        print('SKIP combined newline name/field case: newline in argv is not portable on Windows')
    else:
        run('set', name, field, '--stdin', stdin=SECRET)
        assert run('get', name, field)[0] == {'service': name, 'field': field, 'set': True}
        rows = run('list')[0]
        assert [(r['service'], r['field']) for r in rows] == sorted((r['service'], r['field']) for r in rows)
        assert run('delete', name, field)[0] == {'deleted': True}
    assert run('delete', 'service', 'key')[0] == {'deleted': True}
    assert run('delete', 'service', 'key')[0] == {'deleted': False}
    assert run('get', 'service', 'key')[0]['set'] is False
    run('get', 'service', 'key', '--reveal', code=3, error='NOT_FOUND')

    for args in [[], ['unknown'], ['list', 'extra'], ['path', 'extra'], ['get', 's'],
                 ['get', 's', 'f', '--unknown'], ['get', 's', 'f', '--reveal', '--reveal'],
                 ['delete', 's'], ['delete', 's', 'f', 'extra'], ['set', '', 'f', '--stdin'],
                 ['set', 's', '--field', '--stdin'], ['set', 's', 'f'],
                 ['set', 's', 'f', '--unknown'], ['set', 's', 'f', '--value'],
                 ['set', 's', 'f', '--env'], ['set', 's', 'f', '--value', '--stdin'],
                 ['set', 's', 'f', '--stdin', '--stdin'],
                 ['set', 's', 'f', '--value', SECRET, '--stdin'],
                 ['set', 's', 'f', '--env', 'VAR', '--stdin'],
                 ['set', 's', 'f', '--value', SECRET, '--env', 'VAR']]:
        run(*args, code=2, error='USAGE')

    # Invalid storage errors must not reveal path text or echoed credential input.
    blocked = Path(directory) / 'dummy-path-secret'
    blocked.write_text('a regular file, not a directory', encoding='utf-8')
    bad_env = {'LMCLIENT_DB': str(blocked / 'creds.db')}
    for args in [('list',), ('get', 's', 'f'), ('delete', 's', 'f'), ('set', 's', 'f', '--stdin')]:
        result, _ = run(*args, stdin=SECRET, env=bad_env, code=3, error='CREDENTIAL_ERROR')
        assert result['message'] == 'Credential operation failed'

    # Real cross-language reads/writes use the exact lmconn implementation.
    module = Path(os.environ.get('LMCONN_CREDS_MODULE', str(Path.home() / 'lmworkflow/lmconn/src/creds.js')))
    node = shutil.which('node')
    if not node or not module.is_file():
        print('SKIPPED cross-tool checks: Node or lmconn/src/creds.js is absent (set LMCONN_CREDS_MODULE)')
    else:
        run('set', 'interop', 'key', '--stdin', stdin='dummy-java-to-node')
        script = '''
import { pathToFileURL } from 'node:url';
const { getCred, setCred, closeDb } = await import(pathToFileURL(process.argv[1]).href);
try {
  if (getCred('interop', 'key') !== process.env.EXPECTED_DUMMY) throw new Error('cross-tool mismatch');
  setCred('interop', 'key', process.env.NEXT_DUMMY);
  process.stdout.write('interop ok\\n');
} finally { closeDb(); }
'''
        process = subprocess.run([node, '--input-type=module', '-e', script, str(module)],
                                 env={**BASE_ENV, 'LMCONN_DB': database,
                                      'EXPECTED_DUMMY': 'dummy-java-to-node', 'NEXT_DUMMY': 'dummy-node-to-java'},
                                 capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert process.returncode == 0, 'Node cross-tool check failed'
        assert process.stdout == 'interop ok\n'
        for secret in SECRETS:
            assert secret not in process.stdout + process.stderr
        checks += 1
        assert run('get', 'interop', 'key', '--reveal')[0]['value'] == 'dummy-node-to-java'
        assert run('get', 'interop', 'key')[0]['set'] is True
        run('list')
        print('Java → Node and Node → Java SQLite interoperability: PASS')

print(f'Credential checks: {checks} passed')
