package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.SharedAssets
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Per-vendor role map, model prices and capabilities from `letter_writer/clients/<vendor>.json`. */
class VendorCatalog(val vendor: ModelVendor, private val root: JsonObject) {
    val roles: JsonObject get() = root["roles"].asObjectOrNull() ?: JsonObject(emptyMap())
    val models: JsonObject get() = root["models"].asObjectOrNull() ?: JsonObject(emptyMap())
    val defaults: JsonObject get() = root["defaults"].asObjectOrNull() ?: JsonObject(emptyMap())

    fun modelForRole(role: ModelRole): String {
        val entry = roles[role.value]
            ?: throw IllegalStateException("Model role '${role.value}' not defined in ${vendor.catalogStem}.json")
        return when (entry) {
            is JsonObject -> entry["model"].asStringOrNull()?.takeIf { it.isNotEmpty() }
                ?: throw IllegalStateException("Model role '${role.value}' missing 'model' key in ${vendor.catalogStem}.json")
            else -> entry.asStringOrNull()
                ?: throw IllegalStateException("Model role '${role.value}' in ${vendor.catalogStem}.json is not a string")
        }
    }

    /** Role entry without `model`: the vendor-specific thinking keys. */
    fun thinkingConfig(role: ModelRole): Map<String, JsonElement> {
        val entry = roles[role.value] as? JsonObject ?: return emptyMap()
        return entry.filterKeys { it != "model" }
    }

    /** Exact model id, otherwise the longest configured id contained in [model]. */
    fun matchingModelEntry(model: String): JsonObject {
        if (model.isEmpty()) return JsonObject(emptyMap())
        (models[model] as? JsonObject)?.let { return it }
        val needle = model.lowercase()
        var bestKey = ""
        var best = JsonObject(emptyMap())
        for ((key, entry) in models) {
            if (entry !is JsonObject) continue
            val token = key.lowercase()
            if (token.isNotEmpty() && needle.contains(token) && token.length > bestKey.length) {
                bestKey = token
                best = entry
            }
        }
        return best
    }

    /** Model field, then vendor default, then null (Python `vendor_model_field`). */
    fun modelField(model: String, key: String): JsonElement? {
        matchingModelEntry(model)[key]?.takeIf { it !is JsonNull }?.let { return it }
        return defaults[key]?.takeIf { it !is JsonNull }
    }

    /** Exact-name pricing (Python `BaseClient.get_model_cost`); unknown models price at zero. */
    fun modelCost(model: String): ModelCost {
        val defaultSearch = defaults["search"].asDoubleOrNull() ?: 0.0
        val entry = models[model] as? JsonObject ?: JsonObject(emptyMap())
        val cachedMult = (entry["input_cached_mult"] ?: defaults["input_cached_mult"]).nonZeroOr(0.5)
        val writeMult = (entry["cache_write_mult"] ?: defaults["cache_write_mult"]).nonZeroOr(1.0)
        val searchRaw = entry["search"]
        val search = if (searchRaw != null && searchRaw !is JsonNull) parsePrice(searchRaw) else defaultSearch
        return ModelCost(
            input = parsePrice(entry["input"]),
            output = parsePrice(entry["output"]),
            search = search,
            inputCachedMult = cachedMult,
            cacheWriteMult = writeMult,
            priced = models[model] is JsonObject,
        )
    }

    /**
     * [modelCost] at the short-prompt rate, or the `high` rate when [inputTokens]
     * is over a catalog `threshold`. Haiku 5.5 switches both rates on prompt length.
     */
    fun costForPrompt(model: String, inputTokens: Long): ModelCost {
        val base = modelCost(model)
        val entry = models[model] as? JsonObject ?: return base
        val threshold = promptThreshold(entry["input"]) ?: promptThreshold(entry["output"]) ?: return base
        if (inputTokens <= threshold) return base
        return base.copy(input = highPrice(entry["input"], base.input), output = highPrice(entry["output"], base.output))
    }

    /** Python `get_all_model_pricing` rows for this vendor (models with a price, or free-tier-only). */
    fun modelInfos(): List<ModelInfo> {
        val defaultSearch = defaults["search"].asDoubleOrNull() ?: 0.0
        return models.mapNotNull { (id, raw) ->
            val cfg = raw as? JsonObject ?: return@mapNotNull null
            val input = parsePrice(cfg["input"])
            val output = parsePrice(cfg["output"])
            val freeTierOnly = (cfg["free_tier_only"] as? JsonPrimitive)?.content == "true"
            if (input == 0.0 && output == 0.0 && !freeTierOnly) return@mapNotNull null
            ModelInfo(
                id = id,
                name = id.replace("-", " ").split(" ").joinToString(" ") { w -> w.replaceFirstChar { it.uppercase() } },
                vendor = vendor,
                input = input,
                output = output,
                supportsSearch = supportsSearch(id, cfg, defaultSearch),
                reasoningEfforts = reasoningEfforts(cfg),
                supersededBy = validatedSuccessor(cfg),
                freeTierOnly = freeTierOnly,
            )
        }
    }

    private fun supportsSearch(id: String, cfg: JsonObject, defaultSearch: Double): Boolean =
        when (vendor) {
            ModelVendor.DEEPSEEK -> false
            ModelVendor.OPENAI -> "search" in id
            else -> {
                val raw = cfg["search"]
                if (raw != null && raw !is JsonNull) (raw.asDoubleOrNull() ?: 0.0) > 0.0 else defaultSearch > 0.0
            }
        }

    private fun reasoningEfforts(cfg: JsonObject): List<String> {
        fun list(key: String): List<JsonElement> =
            ((cfg[key] as? JsonArray)?.takeIf { it.isNotEmpty() } ?: (defaults[key] as? JsonArray)).orEmpty()
        return when (vendor) {
            ModelVendor.OPENAI, ModelVendor.GROK, ModelVendor.DEEPSEEK ->
                list("reasoning_efforts").map { (it as? JsonPrimitive)?.content ?: it.toString() }
            ModelVendor.GEMINI -> list("thinking_levels").map {
                val s = (it as? JsonPrimitive)?.takeIf { p -> p !is JsonNull }?.content
                if (s == null || s.trim().lowercase() in setOf("", "none", "null")) "none" else s
            }
            ModelVendor.ANTHROPIC -> list("thinking_efforts").map { (it as? JsonPrimitive)?.content ?: it.toString() }
            ModelVendor.MISTRAL -> emptyList()
        }
    }

    private fun validatedSuccessor(cfg: JsonObject): String? {
        val successor = cfg["superseded_by"].asStringOrNull()?.takeIf { it.isNotEmpty() } ?: return null
        val next = models[successor] as? JsonObject ?: return null
        val cheaperOrEqual = parsePrice(next["input"]) <= parsePrice(cfg["input"]) &&
            parsePrice(next["output"]) <= parsePrice(cfg["output"])
        return if (cheaperOrEqual) successor else null
    }

    companion object {
        fun load(assets: SharedAssets, vendor: ModelVendor): VendorCatalog {
            val text = assets.catalog(vendor.catalogStem)
                ?: throw IllegalStateException("Missing catalog ${vendor.catalogStem}.json in app assets")
            val root = Json.parse(text) as? JsonObject
                ?: throw IllegalStateException("Catalog ${vendor.catalogStem}.json is not a JSON object")
            return VendorCatalog(vendor, root)
        }

        private fun promptThreshold(field: JsonElement?): Long? =
            (field as? JsonObject)?.get("threshold")?.asLongOrNull()

        private fun highPrice(field: JsonElement?, fallback: Double): Double {
            val o = field as? JsonObject ?: return fallback
            return o["high"]?.asDoubleOrNull() ?: o["low"]?.asDoubleOrNull() ?: fallback
        }

        /** Number, or the `low` (else `high`) tier of a `{low, high}` price. */
        fun parsePrice(v: JsonElement?): Double =
            when (v) {
                is JsonPrimitive -> v.asDoubleOrNull() ?: 0.0
                is JsonObject -> (v["low"] ?: v["high"]).asDoubleOrNull() ?: 0.0
                else -> 0.0
            }

        /** Python `float(x or default)`: a missing or zero value falls back. */
        private fun JsonElement?.nonZeroOr(default: Double): Double {
            val d = this.asDoubleOrNull()
            return if (d == null || d == 0.0) default else d
        }
    }
}

data class ModelCost(
    val input: Double,
    val output: Double,
    val search: Double,
    val inputCachedMult: Double,
    val cacheWriteMult: Double,
    /** False when the model has no price entry; the desktop records such calls as $0. */
    val priced: Boolean,
)

data class ModelInfo(
    val id: String,
    val name: String,
    val vendor: ModelVendor,
    val input: Double,
    val output: Double,
    val supportsSearch: Boolean,
    val reasoningEfforts: List<String>,
    val supersededBy: String?,
    val freeTierOnly: Boolean,
) {
    val composite: String get() = "${vendor.key}/$id"
}

class Catalogs(assets: SharedAssets) {
    private val byVendor: Map<ModelVendor, VendorCatalog> =
        ModelVendor.entries.associateWith { VendorCatalog.load(assets, it) }

    operator fun get(vendor: ModelVendor): VendorCatalog = byVendor.getValue(vendor)

    fun allModels(searchOnly: Boolean = false): List<ModelInfo> =
        ModelVendor.entries.sortedBy { it.catalogStem }.flatMap { v ->
            byVendor.getValue(v).modelInfos().filter { !searchOnly || it.supportsSearch }
        }
}
