package ai.lmctl.lmclient.spike;

import dev.langchain4j.model.openai.OpenAiChatModel;

/**
 * LangChain4j spike: one live OpenAI-compatible chat (DeepSeek by default).
 * The JVM run proves API behavior; the CI native build answers the real
 * question — whether langchain4j + Jackson survive GraalVM native-image
 * with hand-written config. SPIKE_BASE_URL / SPIKE_MODEL override the target.
 */
public final class Lc4jSpike {
    public static void main(String[] args) {
        String base = System.getenv().getOrDefault("SPIKE_BASE_URL", "https://api.deepseek.com");
        String model = System.getenv().getOrDefault("SPIKE_MODEL", "deepseek-chat");
        String key = System.getenv("DEEPSEEK_API_KEY");
        if (System.getenv("SPIKE_KEY_ENV") != null) key = System.getenv(System.getenv("SPIKE_KEY_ENV"));
        if (key == null || key.isBlank()) { System.out.println("SKIPPED: no api key env"); return; }
        var chat = OpenAiChatModel.builder()
            .baseUrl(base).apiKey(key).modelName(model).maxTokens(16)
            .build();
        String answer = chat.chat("reply with exactly: pong");
        System.out.println("lc4j answer: " + answer.trim());
    }
}
