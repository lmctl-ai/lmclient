# github area

Read-only GitHub connector, a port of lmconn's `github` ops. Owner: Fable
(wave 6).

```
lmclient github user
lmclient github repos ORG [--limit N]
```

## wiring

- No new Maven dependencies or POM changes: JDK `java.net.http.HttpClient`,
  `ProcessBuilder` for `gh auth token`, the shared `CredStore`, and the
  bundled lmcode SDK's JSON parser.
- Build: `mvn -q -B package -DskipTests`.
- Test: `python3 scripts/test-github.py target/lmclient-0.2.0-all.jar` (also
  accepts a native executable). Offline by default: a loopback Python
  fixture serves canned `/user`, `/orgs/*/repos` and `/users/*/repos`
  responses and records only whether an Authorization header was present.
  Token sources are driven with dummy values: a seeded SQLite store, the
  `GITHUB_TOKEN`/`GH_TOKEN` variables, and a fake `gh` on a private PATH.
  `LMCLIENT_GITHUB_LIVE=1` adds a real call to api.github.com
  (`repos lmctl-ai --limit 3`, plus `user` when a token resolves).
- Test seam: `LMCLIENT_GITHUB_API` overrides the API origin
  (default `https://api.github.com`).
- No reflection metadata; native verification belongs to CI.

## Behaviour

Token resolution, in order, reported as `auth` and `tokenSource` and never as
a value: `store` (`CredStore` `github` / `api_key`), `env:GITHUB_TOKEN`,
`env:GH_TOKEN`, `gh` (`gh auth token`, 5 s limit, stderr discarded),
`anonymous` (rate limited). An unavailable credential store falls through to
the environment instead of failing.

Requests carry `Accept: application/vnd.github+json`, `User-Agent: lmclient`,
`X-GitHub-Api-Version: 2022-11-28`, `Authorization: Bearer` when a token
exists; connect timeout 10 s, response timeout 30 s, redirects followed.

| Command | Result |
|---|---|
| `user` | `{"login","name","id","publicRepos","auth","tokenSource"}`; needs a token |
| `repos ORG [--limit N]` | `{"org","count","names":[...],"repos":[{"name","description","stars"}],"auth","tokenSource"}`; `--limit` 1..1000, default 30; pages through `Link: rel="next"`; a 404 on `/orgs/ORG/repos` falls back once to `/users/ORG/repos` |

| Code | Exit | When |
|---|---|---|
| `USAGE` | 2 | unknown command or option, bad `--limit`, extra arguments |
| `MISSING_KEY` | 3 | `user` without any token (no request is made) |
| `AUTH` | 3 | HTTP 401 or 403; message names the token source and how to store one |
| `NOT_FOUND` | 3 | HTTP 404 (after the user-endpoint fallback for `repos`) |
| `HTTP` | 3 | any other non-2xx status |
| `NETWORK` | 3 | connection failure or timeout |
| `INVALID_RESPONSE` | 3 | repositories endpoint returned a non-list |

Error messages include GitHub's `message` field when present; the token value
is redacted wherever it could appear.

## Reference differences

lmconn's result fields (`login`, `name`, `id`, `publicRepos`, `auth` for user;
`org`, `count`, `names`, `auth` for repos) are kept exactly, so lmscript
programs written against lmconn keep working. Two additions: `tokenSource`
(the same value as `auth`, the name the Java brief pinned) and `repos`, a
list of `{name, description, stars}` summaries alongside `names`.

lmconn reports every non-2xx status as `GITHUB_HTTP`; this port splits it into
`AUTH`, `NOT_FOUND` and `HTTP` as the brief required. Runtime failures exit 3
(the family Java convention) where lmconn exits 1. The API-origin override and
the fixture-based tests replace lmconn's injectable `fetch`/`exec`.
