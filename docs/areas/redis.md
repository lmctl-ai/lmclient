# Redis

The Redis area uses one bounded, plain-socket Jedis connection per command.

## wiring

- Maven dependency: `redis.clients:jedis:5.2.0` (normal compile scope).
- Test invocation: `python3 scripts/test-redis.py target/lmclient-0.2.0-all.jar`.
  The same script accepts a native executable path for CI.
- CI services: `redis:7-alpine`, TCP 6379. The script starts two isolated
  containers with dynamically allocated loopback host ports; one requires a
  dummy password. Docker access is required for live checks. The script always
  removes its containers and skips live checks clearly if Docker is absent.
- Native config: direct `Jedis` + `DefaultJedisClientConfig` calls, no pool,
  Netty, dynamic proxies, or reflection used by this area. No handwritten
  reflection entries needed. Verify with the CI native build, not a local build.

## Commands and results

| Command | Result |
| --- | --- |
| `redis ping` | `{"pong":"PONG"}` |
| `redis get KEY` | `{"value":"..."}` or `{"value":null}` |
| `redis set KEY VALUE [--ttl SECONDS]` | `{"stored":true}` |
| `redis del KEY [KEY...]` | `{"deleted":N}` |
| `redis lpush KEY VALUE [VALUE...]` | `{"length":N}` |
| `redis rpop KEY` | `{"value":"..."}` or `{"value":null}` |
| `redis lrange KEY START STOP` | `{"values":["..."]}` |
| `redis publish CHANNEL MESSAGE` | `{"receivers":N}` |

Each result is wrapped in `{"ok":true,"result":...}`. Errors use
`{"ok":false,"error":{"code":"...","message":"..."}}` and never echo
connection details or server error text. Exit codes: 0 success, 2 `USAGE`,
3 `CONN` or `READONLY`. Missing keys are successful null results.

## Connection and credentials

Use `--url redis://host:6379/0` or `LMCLIENT_REDIS_URL`. The scheme is `redis`
(or `rediss` for TLS), with an optional database index. URL-embedded credentials
are supported, but prefer environment variables or a UTF-8 Java properties file
so passwords do not appear in process arguments. URL credentials are never echoed.

`--credentials-file FILE` (or `LMCLIENT_CREDENTIALS_FILE`) reads `user` and
`password`. `LMCLIENT_USER` / `LMCLIENT_PASSWORD` override that file; the
area-specific `LMCLIENT_REDIS_USER` / `LMCLIENT_REDIS_PASSWORD` override both.
Explicit credentials override corresponding URL credentials.

`--timeout MILLISECONDS` defaults to 10000 and bounds connect and socket reads.
`--readonly` rejects `set`, `del`, `lpush`, `rpop`, and `publish` before connection.
Redis replica READONLY errors also map to `READONLY`. `--ttl` must be a positive
integer and is valid only for `set`. Use `--` before literal operands beginning
with `--`. Options can appear before or after the command/operands.

Example:

```sh
export LMCLIENT_REDIS_URL=redis://127.0.0.1:6379/0
lmclient redis set example hello --ttl 30
lmclient redis get example
lmscript examples/redis_demo.lms
```

Pub/sub subscription, cluster/sentinel routing, and blocking list operations are
outside this command contract. `publish` sends a message and reports recipient
count; it does not wait for acknowledgments.
