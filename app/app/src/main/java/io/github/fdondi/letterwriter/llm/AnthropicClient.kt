package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class AnthropicClient(
    catalog: VendorCatalog,
    overrides: VendorRoleOverrides,
    apiKey: String,
    private val baseUrl: String = "https://api.anthropic.com/v1",
) : BaseLlmClient(ModelVendor.ANTHROPIC, catalog, overrides, apiKey) {

    private fun headers() = mapOf("x-api-key" to apiKey, "anthropic-version" to "2023-06-01")

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
        val thinkingEnabled = thinking["thinking"].asBooleanOrNull() ?: false
        val minTokens = minCacheTokens(model)
        val (sysRaw, usrRaw) = PromptCache.mergePrefixes(systemCachePrefix, cachePrefix)
        val sysCache = sysRaw?.let { PromptCache.prepareCacheBlock(it, minTokens) }
        val usrCache = usrRaw?.let { PromptCache.prepareCacheBlock(it, minTokens) }
        val messages = formatMessages(userMessages, usrCache)
        val systemBlocks = buildJsonArray {
            if (sysCache != null) {
                add(cachedText(sysCache))
                if (system.trim().isNotEmpty()) add(buildJsonObject { put("type", "text"); put("text", system) })
            } else if (system.trim().isNotEmpty()) {
                add(cachedText(system))
            }
        }

        if (responseFormat != null && responseFormat.isNotEmpty()) {
            val jsonSchema = responseFormat["json_schema"].asObjectOrNull()
            val schema = jsonSchema?.get("schema").asObjectOrNull() ?: JsonObject(emptyMap())
            val toolName = jsonSchema?.get("name").asStringOrNull()?.takeIf { it.isNotEmpty() } ?: "phase_output"
            val jsonFields = jsonRequestFields(model, schema, toolName)
            val body = buildJsonObject {
                put("model", model)
                if (systemBlocks.isNotEmpty()) put("system", systemBlocks)
                put("messages", messages)
                put("max_tokens", 4000)
                jsonFields.forEach { (k, v) -> put(k, v) }
            }
            val response = post(body)
            trackUsage(model, listOf(response), searchQueries = 0)
            if ("output_config" in jsonFields) return joinedText(response).ifEmpty { "{}" }
            for (block in response["content"].asArrayOrNull().orEmpty()) {
                val b = block.asObjectOrNull() ?: continue
                if (b["type"].asStringOrNull() == "tool_use") {
                    val input = b["input"].asObjectOrNull()
                    if (input != null) return Json.pyDumps(input)
                }
            }
            return "{}"
        }

        val maxTokens = if (search) 2048 else 8000
        val body = buildJsonObject {
            put("model", model)
            if (systemBlocks.isNotEmpty()) put("system", systemBlocks)
            put("messages", messages)
            if (search) {
                put(
                    "tools",
                    buildJsonArray {
                        add(buildJsonObject { put("type", "web_search_20250305"); put("name", "web_search"); put("max_uses", 5) })
                    },
                )
            }
            put("max_tokens", maxTokens)
            if (!search) thinkingFields(model, thinkingEnabled, maxTokens, thinking).forEach { (k, v) -> put(k, v) }
        }
        val response = post(body)
        val stopReason = response["stop_reason"].asStringOrNull()
        if (search && stopReason == "pause_turn") {
            throw IllegalStateException(
                "Anthropic paused the web-search turn for $model; multi-turn search continuation is not ported to Android",
            )
        }
        trackUsage(model, listOf(response), searchQueries = if (search) 1 else 0)
        val parts = response["content"].asArrayOrNull().orEmpty().mapNotNull {
            it.asObjectOrNull()?.get("text").asStringOrNull()?.takeIf { t -> t.isNotEmpty() }
        }
        if (parts.isEmpty()) {
            if (response["content"].asArrayOrNull().isNullOrEmpty()) return ""
            return "Response contains tool usage but no text content found."
        }
        var full = parts.joinToString("\n\n")
        if (search) {
            full = full.replace(Regex("\n+"), "\n").replace(Regex("\n(?![A-Z*#\\-])"), " ")
        }
        return full
    }

    private suspend fun post(body: JsonObject): JsonObject =
        Http.postJson("Anthropic", "$baseUrl/messages", body, headers()).asObjectOrNull()
            ?: throw IllegalStateException("Anthropic returned a non-object response")

    /** Cache reads at `input_cached_mult`, writes at 125% (5-minute ephemeral). */
    private suspend fun trackUsage(model: String, responses: List<JsonObject>, searchQueries: Long) {
        var input = 0L
        var output = 0L
        var read = 0L
        var write = 0L
        for (r in responses) {
            val u = r["usage"].asObjectOrNull() ?: continue
            input += u["input_tokens"].asLongOrNull() ?: 0
            output += u["output_tokens"].asLongOrNull() ?: 0
            read += u["cache_read_input_tokens"].asLongOrNull() ?: 0
            write += u["cache_creation_input_tokens"].asLongOrNull() ?: 0
        }
        if (input == 0L && output == 0L) return
        val c = catalog.costForPrompt(model, input)
        val regular = maxOf(0, input - read - write)
        val inputCost = regular / 1e6 * c.input + read / 1e6 * c.input * c.inputCachedMult + write / 1e6 * c.input * 1.25
        val cost = inputCost + output / 1e6 * c.output + searchQueries / 1e3 * c.search
        record(model, c.priced, UsageTotals(cost, input, output, read, searchQueries, 1))
    }

    private fun minCacheTokens(model: String): Int =
        catalog.modelField(model, "min_cache_tokens").asLongOrNull()?.toInt() ?: 2048

    private fun jsonRequestFields(model: String, schema: JsonObject, toolName: String): Map<String, JsonElement> {
        val structured = catalog.modelField(model, "structured_output").asBooleanOrNull() ?: false
        if (structured) {
            schemaBlocksJsonOutput(schema)?.let { reason ->
                throw IllegalArgumentException(
                    "Model $model requests JSON via output_config.format, but this schema is not valid for that API ($reason).",
                )
            }
            return mapOf(
                "output_config" to buildJsonObject {
                    put(
                        "format",
                        buildJsonObject {
                            put("type", "json_schema")
                            put("schema", schemaForJsonOutput(schema))
                        },
                    )
                },
            )
        }
        return mapOf(
            "tools" to buildJsonArray {
                add(
                    buildJsonObject {
                        put("name", toolName)
                        put("description", "Return structured JSON response for the current phase.")
                        put("input_schema", schema)
                    },
                )
            },
            "tool_choice" to buildJsonObject { put("type", "tool"); put("name", toolName) },
        )
    }

    private fun thinkingFields(
        model: String,
        enabled: Boolean,
        maxTokens: Int,
        cfg: Map<String, JsonElement>,
    ): Map<String, JsonElement> {
        if (!enabled) {
            val offType = catalog.modelField(model, "thinking_off_type").asStringOrNull()
            return if (!offType.isNullOrEmpty()) mapOf("thinking" to buildJsonObject { put("type", offType) }) else emptyMap()
        }
        val thinkingType = catalog.modelField(model, "thinking_type").asStringOrNull()?.lowercase() ?: "enabled"
        if (thinkingType == "adaptive") {
            return mapOf(
                "thinking" to buildJsonObject { put("type", "adaptive") },
                "output_config" to buildJsonObject { put("effort", adaptiveEffort(model, cfg)) },
            )
        }
        return mapOf(
            "thinking" to buildJsonObject {
                put("type", "enabled")
                put("budget_tokens", maxOf(1, maxTokens / 2))
            },
        )
    }

    /** Catalog ``thinking_efforts`` except ``off``, which means thinking disabled. */
    private fun catalogEfforts(model: String): List<String> {
        val raw = catalog.modelField(model, "thinking_efforts") as? JsonArray ?: return emptyList()
        return raw.mapNotNull { (it as? JsonPrimitive)?.content?.trim()?.lowercase() }
            .filter { it.isNotEmpty() && it !in THINKING_OFF }
    }

    private fun adaptiveEffort(model: String, cfg: Map<String, JsonElement>): String {
        val allowed = catalogEfforts(model)
        val requested = (
            cfg["effort"].asStringOrNull()?.takeIf { it.isNotEmpty() }
                ?: cfg["thinking_effort"].asStringOrNull()?.takeIf { it.isNotEmpty() }
            )?.lowercase()
        if (!requested.isNullOrEmpty() && (allowed.isEmpty() || requested in allowed)) return requested
        val fallback = catalog.modelField(model, "default_thinking_effort").asStringOrNull()?.trim()?.lowercase()
        if (!fallback.isNullOrEmpty() && (allowed.isEmpty() || fallback in allowed)) return fallback
        return allowed.firstOrNull() ?: requested.orEmpty()
    }

    companion object {
        private val THINKING_OFF = setOf("off", "none", "false")

        private fun cachedText(text: String) = buildJsonObject {
            put("type", "text")
            put("text", text)
            put("cache_control", buildJsonObject { put("type", "ephemeral") })
        }

        private fun formatMessages(userMessages: List<String>, cachePrefix: String?): JsonArray = buildJsonArray {
            userMessages.forEachIndexed { i, message ->
                add(
                    buildJsonObject {
                        put("role", "user")
                        put(
                            "content",
                            buildJsonArray {
                                if (i == 0 && cachePrefix != null) add(cachedText(cachePrefix))
                                add(buildJsonObject { put("type", "text"); put("text", message) })
                            },
                        )
                    },
                )
            }
        }

        private fun joinedText(response: JsonObject): String =
            response["content"].asArrayOrNull().orEmpty()
                .mapNotNull { b ->
                    val o = b.asObjectOrNull() ?: return@mapNotNull null
                    if (o["type"].asStringOrNull() == "text") o["text"].asStringOrNull()?.takeIf { it.isNotEmpty() } else null
                }
                .joinToString("")
                .trim()

        /** Why [node] cannot be sent as `output_config.format`, or null. */
        fun schemaBlocksJsonOutput(node: JsonElement): String? {
            when (node) {
                is JsonObject -> {
                    val ap = node["additionalProperties"]
                    if (node["type"].asStringOrNull() == "object" && ap != null && !(ap is JsonPrimitive && ap.asBooleanOrNull() == false)) {
                        return "additionalProperties must be false on every object"
                    }
                    for (v in node.values) schemaBlocksJsonOutput(v)?.let { return it }
                }
                is JsonArray -> for (v in node) schemaBlocksJsonOutput(v)?.let { return it }
                else -> Unit
            }
            return null
        }

        /** Copy [node], closing objects that omit `additionalProperties`. */
        fun schemaForJsonOutput(node: JsonElement): JsonElement =
            when (node) {
                is JsonArray -> JsonArray(node.map { schemaForJsonOutput(it) })
                is JsonObject -> {
                    val copied = LinkedHashMap<String, JsonElement>()
                    node.forEach { (k, v) -> copied[k] = schemaForJsonOutput(v) }
                    if (copied["type"].asStringOrNull() == "object" && "additionalProperties" !in copied) {
                        copied["additionalProperties"] = JsonPrimitive(false)
                    }
                    JsonObject(copied)
                }
                is JsonNull, is JsonPrimitive -> node
            }
    }
}
