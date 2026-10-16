package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
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

class GeminiClient(
    catalog: VendorCatalog,
    overrides: VendorRoleOverrides,
    apiKey: String,
    private val baseUrl: String = "https://generativelanguage.googleapis.com/v1beta",
) : BaseLlmClient(ModelVendor.GEMINI, catalog, overrides, apiKey) {

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
        val systemPrompt = mergeSystemCachePrefixIntoSystem(system, systemCachePrefix)
        val (model, thinking) = resolve(role)
        val thinkingLevel = thinking["thinking_level"].asStringOrNull()
        val messages = userMessages.filter { it.isNotBlank() }
        if (messages.isEmpty()) {
            throw IllegalArgumentException("No valid user messages provided to Gemini API (all were None or empty)")
        }
        val schema = responseFormat?.get("json_schema").asObjectOrNull()?.get("schema").asObjectOrNull()

        val body = buildJsonObject {
            put("system_instruction", buildJsonObject { put("parts", buildJsonArray { add(textPart(systemPrompt)) }) })
            put(
                "contents",
                buildJsonArray {
                    add(
                        buildJsonObject {
                            put("role", "user")
                            put("parts", buildJsonArray { messages.forEach { add(textPart(it)) } })
                        },
                    )
                },
            )
            if (search) put("tools", buildJsonArray { add(buildJsonObject { put("google_search", buildJsonObject { }) }) })
            put(
                "generationConfig",
                buildJsonObject {
                    THINKING_LEVELS[thinkingLevel]?.let { level ->
                        put("thinkingConfig", buildJsonObject { put("thinkingLevel", level) })
                    }
                    if (schema != null && schema.isNotEmpty()) {
                        put("responseMimeType", "application/json")
                        put("responseJsonSchema", stripUnsupportedSchemaKeys(schema))
                    }
                },
            )
        }
        val response = try {
            Http.postJson("Gemini", "$baseUrl/models/$model:generateContent", body, mapOf("x-goog-api-key" to apiKey))
                .asObjectOrNull() ?: throw IllegalStateException("Gemini returned a non-object response")
        } catch (e: Exception) {
            throw RuntimeException("Gemini generate_content failed: ${e.message}", e)
        }

        val candidate = response["candidates"].asArrayOrNull()?.firstOrNull().asObjectOrNull()
        response["usageMetadata"].asObjectOrNull()?.let { usage ->
            val thoughts = usage["thoughtsTokenCount"].asLongOrNull() ?: 0
            val output = (usage["candidatesTokenCount"].asLongOrNull() ?: 0) + thoughts
            val cached = usage["cachedContentTokenCount"].asLongOrNull() ?: 0
            var searchQueries = 0L
            if (search && candidate != null) {
                searchQueries = candidate["groundingMetadata"].asObjectOrNull()?.get("webSearchQueries")
                    .asArrayOrNull()?.size?.toLong() ?: 0
                if (searchQueries == 0L) searchQueries = 1
            }
            track(model, usage["promptTokenCount"].asLongOrNull() ?: 0, output, searchQueries, cached)
        }

        val parts = candidate?.get("content").asObjectOrNull()?.get("parts").asArrayOrNull().orEmpty()
            .mapNotNull { it.asObjectOrNull() }
            .filter { it["thought"].asBooleanOrNull() != true }
            .mapNotNull { it["text"].asStringOrNull() }
        if (parts.isEmpty()) {
            val finish = candidate?.get("finishReason").asStringOrNull()
            throw RuntimeException(
                "Gemini API returned no text content" + (finish?.let { " (finish_reason: $it)" } ?: ""),
            )
        }
        return parts.joinToString("")
    }

    /** Python `GeminiClient.track_cost`: input and output tiers checked against their own thresholds. */
    private suspend fun track(model: String, input: Long, output: Long, searchQueries: Long, cached: Long) {
        val defaults = catalog.defaults
        val defaultSearch = defaults["search"].asDoubleOrNull() ?: 0.0
        val defaultThreshold = defaults["threshold"].asLongOrNull() ?: 0
        val defaultCachedMult = defaults["input_cached_mult"].asDoubleOrNull()?.takeIf { it != 0.0 } ?: 1.0
        val entry = catalog.models[model].asObjectOrNull()
        val cfg = entry ?: JsonObject(emptyMap())

        val inP = tier(cfg["input"], defaultThreshold)
        val outP = tier(cfg["output"], defaultThreshold)
        val inputPrice = if (input > inP.threshold) inP.high else inP.low
        val outputPrice = if (output > outP.threshold) outP.high else outP.low
        val search = (cfg["search"]?.asDoubleOrNull() ?: defaultSearch)
        val cachedMult = cfg["input_cached_mult"].asDoubleOrNull()?.takeIf { it != 0.0 } ?: defaultCachedMult

        val uncached = maxOf(0, input - cached)
        val cost = uncached / 1e6 * inputPrice + cached / 1e6 * inputPrice * cachedMult +
            output / 1e6 * outputPrice + searchQueries / 1e3 * search
        record(model, entry != null, UsageTotals(cost, input, output, cached, searchQueries, 1))
    }

    private data class Tier(val low: Double, val high: Double, val threshold: Long)

    private fun tier(field: JsonElement?, defaultThreshold: Long): Tier =
        when (field) {
            is JsonObject -> {
                val low = field["low"].asDoubleOrNull() ?: 0.0
                val high = field["high"]?.asDoubleOrNull() ?: low
                Tier(low, high, field["threshold"].asLongOrNull() ?: defaultThreshold)
            }
            is JsonPrimitive -> {
                val v = field.asDoubleOrNull() ?: 0.0
                Tier(v, v, defaultThreshold)
            }
            else -> Tier(0.0, 0.0, defaultThreshold)
        }

    companion object {
        private val THINKING_LEVELS = mapOf("Minimal" to "MINIMAL", "Low" to "LOW", "Medium" to "MEDIUM", "High" to "HIGH")
        private val UNSUPPORTED_SCHEMA_KEYS = setOf("minLength", "maxLength")

        private fun textPart(text: String) = buildJsonObject { put("text", text) }

        fun stripUnsupportedSchemaKeys(schema: JsonElement): JsonElement =
            when (schema) {
                is JsonObject -> JsonObject(
                    schema.filterKeys { it !in UNSUPPORTED_SCHEMA_KEYS }.mapValues { stripUnsupportedSchemaKeys(it.value) },
                )
                is JsonArray -> JsonArray(schema.map { stripUnsupportedSchemaKeys(it) })
                else -> schema
            }
    }
}
