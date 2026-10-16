package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.ApiKeys

/** Python `get_client(vendor)` + bound role overrides. */
class ClientFactory(
    private val catalogs: Catalogs,
    private val keys: ApiKeys,
    private val overrides: VendorRoleOverrides,
) {
    fun create(vendor: ModelVendor): LlmClient {
        val catalog = catalogs[vendor]
        val key = keys.require(keyField(vendor), "${vendor.label} calls")
        return when (vendor) {
            ModelVendor.OPENAI -> OpenAiClient(catalog, overrides, key)
            ModelVendor.ANTHROPIC -> AnthropicClient(catalog, overrides, key)
            ModelVendor.GEMINI -> GeminiClient(catalog, overrides, key)
            ModelVendor.MISTRAL -> MistralClient(catalog, overrides, key)
            ModelVendor.GROK -> GrokClient(catalog, overrides, key)
            ModelVendor.DEEPSEEK -> DeepSeekClient(catalog, overrides, key)
        }
    }

    fun hasKey(vendor: ModelVendor): Boolean = keys.has(keyField(vendor))

    companion object {
        fun keyField(vendor: ModelVendor): String =
            when (vendor) {
                ModelVendor.OPENAI -> ApiKeys.OPENAI
                ModelVendor.ANTHROPIC -> ApiKeys.ANTHROPIC
                ModelVendor.GEMINI -> ApiKeys.GEMINI
                ModelVendor.MISTRAL -> ApiKeys.MISTRAL
                ModelVendor.GROK -> ApiKeys.XAI
                ModelVendor.DEEPSEEK -> ApiKeys.DEEPSEEK
            }
    }
}
