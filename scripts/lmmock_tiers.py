"""Additional real-process HTTP and OAuth tiers, shared by JVM/native runs."""
import importlib.util
import json
from pathlib import Path
import socket

spec = importlib.util.spec_from_file_location('lmmock_helpers', Path(__file__).with_name('lmmock-helpers.py'))
mock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mock)


def http_tier(run):
    mock.locate_lmmock()
    with mock.lmmock_serve(Path(__file__).parent / 'mocks/http.lms') as base:
        assert run('request', base + '/health')['bodyJson'] == {'ok': True}
        result = run('request', base + '/echo', '--data', 'hello')
        assert result['status'] == 201 and result['bodyText'] == 'hello'
        assert run('request', base + '/headers', '--header', 'X-Test: roundtrip')['bodyText'] == 'roundtrip'
        for status in (404, 429, 503):
            result = run('request', base + f'/status/{status}')
            assert result['status'] == status and result['ok'] is False
        assert run('request', base + '/redirect')['status'] == 302
    print('PASS 7 lmmock HTTP checks: health, echo, headers, statuses, redirect')


def oauth_tier(directory, authorize, run, get, put, protected):
    mock.locate_lmmock()
    source = mock.oauth_source(directory)
    count = 0
    for mode, style, form in [('', 'header', False), ('', 'body', True),
                              ('bad-state', 'header', False), ('bad-json', 'header', False),
                              ('server-error', 'header', False), ('string-expires', 'header', False),
                              ('missing-expiry', 'header', False), ('extra-fields', 'header', False)]:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        log = Path(directory) / 'audit.jsonl'
        log.write_text('', encoding='utf-8')
        config = {'clients': {'mock-client': {'clientSecret': 'dummy-oauth-client-secret',
                  'redirectUris': [f'http://127.0.0.1:{port}/callback'], 'authStyle': style}},
                  'requirePkce': True, 'rotateRefreshTokens': True, 'formEncodedTokenResponse': form,
                  'misbehave': mode, 'logFile': str(log)}
        with mock.lmmock_serve(source, config) as base:
            urls = {'authUrl': base + '/authorize', 'tokenUrl': base + '/token', 'userinfoUrl': base + '/api/userinfo'}
            service = 'lmmock-' + (mode or style)
            failure = mode in ('bad-state', 'bad-json', 'server-error')
            result = authorize(service, urls, port, '--scope', 'read write', '--auth-style', style,
                               expected=3 if failure else 0, error='OAUTH_ERROR' if failure else None)
            events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            assert [e['path'] for e in events] == (['/authorize'] if mode == 'bad-state' else ['/authorize', '/token'])
            assert events[0]['params']['code_challenge_method'] == 'S256'
            assert len(events[0]['params']['code_challenge']) == 43
            if failure:
                assert not run('status', service)['authorized']
            else:
                assert events[1]['authStyle'] == style
                assert result['scope'] == 'read write' and result['hasRefreshToken']
                assert (result['expiresAt'] is None) == (mode == 'missing-expiry')
                protected(service, urls)
                old = get(service, 'oauth_refresh_token')
                run('refresh', service)
                assert get(service, 'oauth_refresh_token') != old
                protected(service, urls)
                put(service, 'oauth_refresh_token', 'revoked-refresh-secret')
                run('refresh', service, expected=3, error='RECONNECT')
            count += 1
    print(f'PASS {count} lmmock OAuth scenarios: PKCE, header/body/form, userinfo, rotation, revoked grants, state and token faults')
