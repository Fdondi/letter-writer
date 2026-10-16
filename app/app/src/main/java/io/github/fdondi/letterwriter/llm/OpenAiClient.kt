package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class OpenAiClient(
    catalog: VendorCatalog,
    overrides: VendorRoleOverrides,
    apiKey: String,
    private val baseUrl: String = "https://api.openai.com/v1",
) : BaseLlmClient(ModelVendor.OPENAI, catalog, overrides, apiKey) {

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
        val (model, thinking) = resolve(role)
        val reasoningEffort = thinking["reasoning_effort"].asStringOrNull()
        val built = buildMessages(system, userMessages, cachePrefix, systemCachePrefix, model)

        val body = buildJsonObject {
            put("model", model)
            put("messages", built.messages)
            if (responseFormat != null && responseFormat.isNotEmpty()) put("response_format", responseFormat)
            if (!reasoningEffort.isNullOrEmpty() && (reasoningEffort != "none" || acceptsNoneEffort(model))) {
                put("reasoning_effort", reasoningEffort)
            }
            val routingKey = promptCacheKey?.takeIf { it.isNotEmpty() } ?: built.cacheKey
            if (built.explicit && routingKey != null) {
                put("prompt_cache_options", buildJsonObject { put("mode", "explicit") })
                put("prompt_cache_key", routingKey)
            } else if (routingKey != null && !supportsExplicitPromptCache(model)) {
                put("prompt_cache_key", routingKey)
            }
        }
        val response = Http.postJson("OpenAI", "$baseUrl/chat/completions", body, bearer()).asObjectOrNull()
            ?: throw IllegalStateException("OpenAI returned a non-object response")

        response["usage"].asObjectOrNull()?.let { usage ->
            val details = usage["prompt_tokens_details"].asObjectOrNull()
            val cacheRead = details?.get("cached_tokens").asLongOrNull() ?: 0
            val cacheWrite = details?.get("cache_write_tokens").asLongOrNull() ?: 0
            track(
                model,
                usage["prompt_tokens"].asLongOrNull() ?: 0,
                usage["completion_tokens"].asLongOrNull() ?: 0,
                searchQueries = if (search) 1 else 0,
                cachedTokens = cacheRead,
                cacheWriteTokens = cacheWrite,
            )
        }
        val content = response["choices"].asArrayOrNull()?.firstOrNull().asObjectOrNull()
            ?.get("message").asObjectOrNull()?.get("content").asStringOrNull()
            ?: throw IllegalStateException("OpenAI response for $model has no message content")
        return content.trim()
    }

    private suspend fun track(
        model: String,
        inputTokens: Long,
        outputTokens: Long,
        searchQueries: Long,
        cachedTokens: Long,
        cacheWriteTokens: Long,
    ) {
        val c = catalog.modelCost(model)
        val regular = maxOf(0, inputTokens - cachedTokens - cacheWriteTokens)
        val inputCost = regular / 1e6 * c.input +
            cachedTokens / 1e6 * c.input * c.inputCachedMult +
            cacheWriteTokens / 1e6 * c.input * c.cacheWriteMult
        val cost = inputCost + outputTokens / 1e6 * c.output + searchQueries / 1e3 * c.search
        record(model, c.priced, UsageTotals(cost, inputTokens, outputTokens, cachedTokens, searchQueries, 1))
    }

    private fun acceptsNoneEffort(model: String): Boolean {
        val efforts = catalog.matchingModelEntry(model)["reasoning_efforts"] as? JsonArray ?: return false
        return efforts.any { it.asStringOrNull() == "none" }
    }

    data class BuiltMessages(val messages: JsonArray, val cacheKey: String?, val explicit: Boolean)

    companion object {
        private const val MIN_CACHE_TOKENS = 1024
        private val EXPLICIT_CACHE_FAMILIES = listOf("gpt-5.6", "gpt-6")

        fun supportsExplicitPromptCache(model: String): Boolean {
            val m = model.lowercase().trim()
            return EXPLICIT_CACHE_FAMILIES.any { fam ->
                m == fam || (m.startsWith(fam) && m.length > fam.length && m[fam.length] in "-.")
            }
        }

        private fun textBlock(text: String, breakpoint: Boolean = false): JsonObject = buildJsonObject {
            put("type", "text")
            put("text", text)
            if (breakpoint) put("prompt_cache_breakpoint", buildJsonObject { put("mode", "explicit") })
        }

        /** Python `build_openai_messages`. */
        fun buildMessages(
            system: String,
            userMessages: List<String>,
            cachePrefix: String?,
            systemCachePrefix: String?,
            model: String,
        ): BuiltMessages {
            val (sysRaw, usrRaw) = PromptCache.mergePrefixes(systemCachePrefix, cachePrefix)
            val systemBody = system.trim()
            val sysPrefix = sysRaw?.let { PromptCache.prepareCacheBlock(it, MIN_CACHE_TOKENS) }
            val usrPrefix = usrRaw?.let { PromptCache.prepareCacheBlock(it, MIN_CACHE_TOKENS) }
            val key = if (sysRaw != null || usrRaw != null) PromptCache.promptCacheKey(sysRaw, usrRaw) else null

            if (supportsExplicitPromptCache(model) && (sysPrefix != null || usrPrefix != null)) {
                val messages = buildJsonArray {
                    if (sysPrefix != null || systemBody.isNotEmpty()) {
                        add(
                            buildJsonObject {
                                put("role", "system")
                                put(
                                    "content",
                                    buildJsonArray {
                                        if (sysPrefix != null) add(textBlock(sysPrefix, breakpoint = true))
                                        if (systemBody.isNotEmpty()) add(textBlock(systemBody))
                                    },
                                )
                            },
                        )
                    }
                    userMessages.forEachIndexed { i, message ->
                        val text = message.trim()
                        if (i == 0 && usrPrefix != null) {
                            add(
                                buildJsonObject {
                                    put("role", "user")
                                    put(
                                        "content",
                                        buildJsonArray {
                                            add(textBlock(usrPrefix, breakpoint = true))
                                            if (text.isNotEmpty()) add(textBlock(text))
                                        },
                                    )
                                },
                            )
                        } else if (text.isNotEmpty()) {
                            add(userMessage(text))
                        }
                    }
                }
                return BuiltMessages(messages, key, true)
            }

            val merged = sysPrefix ?: usrPrefix
            val systemPrompt = mergeSystemCachePrefixIntoSystem(system, merged)
            val messages = buildJsonArray {
                add(buildJsonObject { put("role", "system"); put("content", systemPrompt) })
                for (message in userMessages) {
                    val text = message.trim()
                    if (text.isNotEmpty()) add(userMessage(text))
                }
            }
            return BuiltMessages(messages, key, false)
        }

        private fun userMessage(text: String): JsonElement = buildJsonObject {
            put("role", "user")
            put("content", JsonPrimitive(text))
        }
    }
}
