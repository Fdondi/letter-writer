package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.HttpStatusException
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Mistral, Grok and DeepSeek all expose an OpenAI-style `/chat/completions` endpoint. */
private fun chatMessages(system: String, userMessages: List<String>): JsonArray = buildJsonArray {
    add(buildJsonObject { put("role", "system"); put("content", system) })
    userMessages.forEach { m -> add(buildJsonObject { put("role", "user"); put("content", m) }) }
}

private fun firstMessageContent(response: JsonObject): String? =
    response["choices"].asArrayOrNull()?.firstOrNull().asObjectOrNull()
        ?.get("message").asObjectOrNull()?.get("content").asStringOrNull()

private fun searchUnsupported(vendor: ModelVendor): Nothing =
    throw UnsupportedOperationException(
        "${vendor.label} web search is not available on Android; the desktop uses the vendor SDK's agent tools for it",
    )

class MistralClient(
    catalog: VendorCatalog,
    overrides: VendorRoleOverrides,
    apiKey: String,
    private val baseUrl: String = "https://api.mistral.ai/v1",
) : BaseLlmClient(ModelVendor.MISTRAL, catalog, overrides, apiKey) {
    override suspend fun call(
        role: RoleRef,
        system: String,
        userMessages: List<String>,
        search: Boolean,
        responseFormat: JsonObject?,
        cachePrefix: String?,
        systemCachePrefix: String?,
        promptCacheKey: String?,
    ): String {
        if (search) searchUnsupported(vendor)
        val systemPrompt = mergeSystemCachePrefixIntoSystem(system, systemCachePrefix)
        val (model, _) = resolve(role)
        val body = buildJsonObject {
            put("model", model)
            put("messages", chatMessages(systemPrompt, userMessages))
            if (responseFormat != null && responseFormat.isNotEmpty()) {
                put("response_format", buildJsonObject { put("type", "json_object") })
            }
        }
        val response = try {
            Http.postJson("Mistral", "$baseUrl/chat/completions", body, bearer()).asObjectOrNull()
                ?: throw IllegalStateException("Mistral returned a non-object response")
        } catch (e: HttpStatusException) {
            if (e.status == 401) {
                throw RuntimeException(
                    "Mistral API rejected the stored Mistral key (401 Unauthorized). " +
                        "Create a new key at https://console.mistral.ai/api-keys/ and save it in Settings.",
                    e,
                )
            }
            throw e
        }
        val usage = response["usage"].asObjectOrNull()
        trackStandard(model, usage?.get("prompt_tokens").asLongOrNull() ?: 0, usage?.get("completion_tokens").asLongOrNull() ?: 0)
        return firstMessageContent(response)?.trim().orEmpty()
    }
}

class GrokClient(
    catalog: VendorCatalog,
    overrides: VendorRoleOverrides,
    apiKey: String,
    private val baseUrl: String = "https://api.x.ai/v1",
) : BaseLlmClient(ModelVendor.GROK, catalog, overrides, apiKey) {
    override suspend fun call(
        role: RoleRef,
        system: String,
        userMessages: List<String>,
        search: Boolean,
        responseFormat: JsonObject?,
        cachePrefix: String?,
        systemCachePrefix: String?,
        promptCacheKey: String?,
    ): String {
        if (search) searchUnsupported(vendor)
        val systemPrompt = mergeSystemCachePrefixIntoSystem(system, systemCachePrefix)
        val (model, thinking) = resolve(role)
        val reasoningEffort = thinking["reasoning_effort"].asStringOrNull()
        val body = buildJsonObject {
            put("model", model)
            put("messages", chatMessages(systemPrompt, userMessages))
            if (!reasoningEffort.isNullOrEmpty()) put("reasoning_effort", reasoningEffort)
            xaiResponseFormat(responseFormat)?.let { put("response_format", it) }
        }
        val response = Http.postJson("Grok", "$baseUrl/chat/completions", body, bearer()).asObjectOrNull()
            ?: throw IllegalStateException("Grok returned a non-object response")
        response["usage"].asObjectOrNull()?.let { usage ->
            trackStandard(
                model,
                usage["prompt_tokens"].asLongOrNull() ?: 0,
                usage["completion_tokens"].asLongOrNull() ?: 0,
                cachedTokens = usage["prompt_tokens_details"].asObjectOrNull()?.get("cached_tokens").asLongOrNull() ?: 0,
            )
        }
        return firstMessageContent(response)?.trim()
            ?: throw IllegalStateException("Grok response for $model has no message content")
    }

    private fun xaiResponseFormat(rf: JsonObject?): JsonObject? {
        if (rf == null || rf.isEmpty()) return null
        return when (rf["type"].asStringOrNull()) {
            "json_schema" -> {
                val js = rf["json_schema"].asObjectOrNull()
                val schema = js?.get("schema").asObjectOrNull()
                if (schema != null && schema.isNotEmpty()) {
                    buildJsonObject {
                        put("type", "json_schema")
                        put(
                            "json_schema",
                            buildJsonObject {
                                put("name", js?.get("name").asStringOrNull() ?: "phase_output")
                                put("schema", schema)
                            },
                        )
                    }
                } else {
                    buildJsonObject { put("type", "json_object") }
                }
            }
            "json_object" -> buildJsonObject { put("type", "json_object") }
            else -> null
        }
    }
}

class DeepSeekClient(
    catalog: VendorCatalog,
    overrides: VendorRoleOverrides,
    apiKey: String,
    private val baseUrl: String = "https://api.deepseek.com",
) : BaseLlmClient(ModelVendor.DEEPSEEK, catalog, overrides, apiKey) {
    override suspend fun call(
        role: RoleRef,
        system: String,
        userMessages: List<String>,
        search: Boolean,
        responseFormat: JsonObject?,
        cachePrefix: String?,
        systemCachePrefix: String?,
        promptCacheKey: String?,
    ): String {
        if (search) searchUnsupported(vendor)
        val systemPrompt = mergeSystemCachePrefixIntoSystem(system, systemCachePrefix)
        val (model, thinking) = resolve(role)
        val reasoningEffort = thinking["reasoning_effort"].asStringOrNull()
        val body = buildJsonObject {
            put("model", model)
            put("messages", chatMessages(systemPrompt, userMessages))
            put("stream", false)
            if (responseFormat != null && responseFormat.isNotEmpty()) {
                put("response_format", buildJsonObject { put("type", "json_object") })
            }
            when (reasoningEffort) {
                "none" -> put("thinking", buildJsonObject { put("type", "disabled") })
                "low", "high", "max" -> {
                    put("reasoning_effort", reasoningEffort)
                    put("thinking", buildJsonObject { put("type", "enabled") })
                }
            }
        }
        val response = Http.postJson("DeepSeek", "$baseUrl/chat/completions", body, bearer()).asObjectOrNull()
            ?: throw IllegalStateException("DeepSeek returned a non-object response")
        response["usage"].asObjectOrNull()?.let { usage ->
            val hit = usage["prompt_cache_hit_tokens"].asLongOrNull() ?: 0
            val cached = if (hit != 0L) hit else usage["prompt_tokens_details"].asObjectOrNull()?.get("cached_tokens").asLongOrNull() ?: 0
            trackStandard(model, usage["prompt_tokens"].asLongOrNull() ?: 0, usage["completion_tokens"].asLongOrNull() ?: 0, cachedTokens = cached)
        }
        return firstMessageContent(response)?.trim()
            ?: throw IllegalStateException("DeepSeek response for $model has no message content")
    }
}
