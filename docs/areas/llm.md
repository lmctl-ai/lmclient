# LLM providers, chat and probe

```
lmclient llm providers
lmclient llm chat PROVIDER [--model M] [--system S] [--max-tokens N] [--timeout MS] [--prompt P | --prompt-file F | --stdin]
lmclient llm probe [PROVIDER ...]
```

Without a prompt option, chat reads UTF-8 stdin. Probe defaults to all seven providers and continues after failures. It sends `Reply with exactly: pong`, with an API token limit of 200, and returns provider/kind/ok/reply/error/latencyMs entries; replies are redacted before truncation to 80 characters.

The source table is copied from lmconn: DeepSeek `https://api.deepseek.com` / `deepseek-flash`; OpenRouter `https://openrouter.ai/api/v1` / `nvidia/nemotron-3.5-lightning:free`; Ollama Cloud `https://ollama.com/v1` / `gpt-oss:20b-cloud`. Append `/chat/completions` to each exact base URL. API keys resolve through `CredStore` field `api_key` first, then `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, or `OLLAMA_API_KEY`. Provider listings report source only; chat reports `keySource`, never key values.

API requests send model/max_tokens/messages, preserve response model/usage, and retry HTTP 429 exactly once after three seconds, within the original timeout. Default timeout is 120 seconds and max tokens is 256. Redirects are not followed, to avoid forwarding credentials. `LMCLIENT_LLM_DEEPSEEK_BASE_URL`, `LMCLIENT_LLM_OPENROUTER_BASE_URL`, and `LMCLIENT_LLM_OLLAMA_CLOUD_BASE_URL` explicitly override base URLs for private gateways or offline fixtures; only HTTP(S) URLs without userinfo/query/fragment are accepted. Set overrides only for trusted endpoints; the selected key is sent there.

CLI argv are exactly `claude -p PROMPT`, `codex exec --skip-git-repo-check PROMPT`, `agy -p PROMPT`, and `kimi -p PROMPT`. System text is prepended as `SYSTEM\n\nPROMPT`. ProcessBuilder uses argument arrays, the system temp directory as cwd, closed stdin, and separate drained stdout/stderr. Timeout defaults: Codex 240 seconds; other CLIs 180 seconds. Timed-out processes and available descendants are forcibly terminated. Stderr errors include at most 500 characters after redaction. CLI model overrides are ignored, matching lmconn; result model is null and keySource is `none`.

## wiring

- No Maven dependencies or POM changes. JDK HttpClient/ProcessBuilder plus existing CredStore, Envelope, and bundled reflection-free SDK JSON parser.
- Build: `mvn -q -B package -DskipTests`.
- Offline test: `python3 scripts/test-llm.py target/lmclient-0.2.0-all.jar` (native executables accepted too). Python loopback HTTP fixtures and temporary PATH executables; temporary SQLite DB, dummy secrets. POSIX CLI shebang fixtures skip explicitly on Windows; API fixtures still run.
- Optional live gate: `LMCLIENT_TEST_LLM_LIVE=1 python3 scripts/test-llm.py target/lmclient-0.2.0-all.jar`. A comma-separated provider list is also accepted. Requires installed/signed-in CLIs and API env keys. No real calls happen by default. This runner prints only provider/pass/fail/code/latency metadata, never raw child stderr or token values.
- No native configuration added. Native verification belongs to CI; local verification is JVM-only.

## Deliberate differences and bounds

The pinned Java task adds `--timeout` and one 429 retry; lmconn's adapter does not retry and its command does not expose timeout. Java runtime errors exit 3 rather than 1. Source metadata is included for CLI replies as `none`. API redirects are refused. Prompt files/stdin are capped at 1 MiB, each CLI output stream at 2 MiB, and API responses at 10 MiB to bound memory. Failures use sanitized coded envelopes; known API keys, secret-shaped environment values, and Bearer strings are redacted from results/errors, including nested usage data. The existing SDK JSON parser rejects duplicate keys and nesting over 128. No streaming, tool calling, attachments, or native-image verification is added in this wave.
