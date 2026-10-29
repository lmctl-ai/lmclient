# LangChain4j spike: deferred, 2026-10-29

Branch `spike/langchain4j` tested whether LangChain4j 1.0.0 should back the
`llm` area and give lmclient dozens of API providers for free.

## Verdict: deferred (branch kept, not merged)

- JVM side: works. `OpenAiChatModel` with a custom `baseUrl` chatted live
  with DeepSeek on the first try, so every OpenAI-compatible provider is one
  builder call on the JVM.
- Native side: fails on all five platforms, and not for missing reflection
  metadata. The repo's deliberate headless guard
  `-H:AbortOnTypeReachable=java.awt.Toolkit` (it keeps the binary small and
  AWT-free) aborts the build because LangChain4j's core reaches
  `java.awt.Toolkit` — almost certainly through its image/document
  utilities (`javax.imageio` territory). Fixing it means either dropping
  the headless guard for the whole tool or substituting away library code
  we don't own; neither is worth it while the guard protects every area.

## What we do instead

The `llm` area stays hand-rolled on `java.net.http` (~150 lines for the
OpenAI-compatible api kind) plus the CLI adapters for claude/codex/agy/kimi,
which LangChain4j cannot provide anyway — our differentiator is wrapping the
agent CLIs (real subscriptions), not just API keys.

Revisit triggers: a provider we need exists only as a LangChain4j
integration, or LangChain4j splits its AWT-touching utilities into an
optional module.

## Kafka spike contrast

Same branch-through-CI pattern, opposite outcome: `spike/kafka` passed
native builds on all five platforms after one metadata fix (five serializer
constructor registrations + one resource entry), with live broker
round-trips on both Linux architectures. Kafka was promoted to a real area
from that evidence. The pattern — JVM proof locally, native verdict in CI,
one bounded fix round — is now the default for any heavy new dependency.
