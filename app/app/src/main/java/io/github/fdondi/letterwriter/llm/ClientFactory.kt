package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.ApiKeys

/**
 * Python `get_client(vendor)` + bound role overrides.
 *
 * [debugClient] is set only while the debug harness is on. It replaces the paid
 * client and does not read an API key. Left null, [create] always uses the real vendor.
 */
class ClientFactory(
    private val catalogs: Catalogs,
    private val keys: ApiKeys,
    private val overrides: VendorRoleOverrides,
    private val debugClient: ((ModelVendor) -> LlmClient)? = null,
) {
    fun create(vendor: ModelVendor): LlmClient {
        debugClient?.let { return it(vendor) }
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

    /** [create] would succeed: a stand-in client is set, or the vendor's key is saved. */
    fun canCreate(vendor: ModelVendor): Boolean = debugClient != null || hasKey(vendor)

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
