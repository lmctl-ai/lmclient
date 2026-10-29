package ai.lmctl.lmclient.areas;

/**
 * llm area — port of lmconn's llm providers/chat/probe.
 * PINNED CLI contract (wave 6; owner Fable; details docs/areas/llm.md):
 *   lmclient llm providers
 *   lmclient llm chat PROVIDER [--model M] [--prompt P | --prompt-file F] [--system S] [--max-tokens N] [--timeout MS]
 *   lmclient llm probe [PROVIDER...]
 * Providers (port lmconn's table): api kind = deepseek, openrouter, ollama-cloud (OpenAI-compatible
 * HTTPS via java.net.http, key via CredStore field api_key then <SERVICE>_API_KEY env); cli kind =
 * claude, codex, agy, kimi (ProcessBuilder, argv array, never shell; prompt as final argv element;
 * timeout kills). Result: {"text","model","usage"?,"latencyMs","keySource","provider"} — lmconn-compatible.
 */
public final class LlmArea {
    private LlmArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "llm area not implemented yet"); }
}
