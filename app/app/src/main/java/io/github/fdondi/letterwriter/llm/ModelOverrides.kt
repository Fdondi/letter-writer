package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.asStringOrNull
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** vendor key -> role -> composite `vendor/model[@thinking]`. */
typealias VendorRoleOverrides = Map<String, Map<String, String>>

/** Port of `phase_model_settings.py` and `clients/model_override.py`. */
class ModelOverrides(private val catalogs: Catalogs) {
    fun roleDefaults(role: String): Map<String, String> {
        val fallbacks = ROLE_FALLBACKS[role].orEmpty()
        val out = LinkedHashMap<String, String>()
        for (vendor in ModelVendor.entries.sortedBy { it.catalogStem }) {
            val roles = catalogs[vendor].roles
            var composite = compositeFromRoleEntry(vendor.key, roles[role])
            if (composite == null) {
                for (fb in fallbacks) {
                    composite = compositeFromRoleEntry(vendor.key, roles[fb])
                    if (composite != null) break
                }
            }
            if (composite != null) out[vendor.key] = composite
        }
        return out
    }

    /** Python `normalize_vendor_role_model_overrides`: drops unknown vendors/roles, expands vendor-only values. */
    fun normalize(raw: JsonElement?): VendorRoleOverrides {
        val obj = raw as? JsonObject ?: return emptyMap()
        val out = LinkedHashMap<String, Map<String, String>>()
        for ((vendor, roles) in obj) {
            val vendorKey = vendor.trim().lowercase()
            if (vendorKey !in VALID_VENDOR_KEYS || roles !is JsonObject) continue
            val cleaned = LinkedHashMap<String, String>()
            for (role in CONFIGURABLE_VENDOR_ROLES) {
                val v = roles[role] ?: continue
                val value = (v.asStringOrNull() ?: (v as? JsonPrimitive)?.content ?: "").trim()
                if (value.isEmpty()) continue
                normalizeModelKey(value, roleDefaults(role))?.let { cleaned[role] = it }
            }
            if (cleaned.isNotEmpty()) out[vendorKey] = cleaned
        }
        return out
    }

    /** vendor -> role -> effective composite (config default unless overridden). */
    fun merged(overrides: VendorRoleOverrides): Map<String, Map<String, String>> {
        val merged = LinkedHashMap<String, MutableMap<String, String>>()
        for (role in CONFIGURABLE_VENDOR_ROLES) {
            for ((vendor, composite) in roleDefaults(role)) {
                merged.getOrPut(vendor) { LinkedHashMap() }[role] = composite
            }
        }
        for ((vendor, roleMap) in overrides) {
            val target = merged.getOrPut(vendor) { LinkedHashMap() }
            for (role in CONFIGURABLE_VENDOR_ROLES) {
                roleMap[role]?.trim()?.takeIf { it.isNotEmpty() }?.let { target[role] = it }
            }
        }
        return merged
    }

    /** Python `apply_stored_role_override`: replace [composite] only when it is that role's default. */
    fun applyStoredRoleOverride(composite: String, role: String, overrides: VendorRoleOverrides): String {
        val raw = composite.trim()
        if (raw.isEmpty()) return raw
        val vendor = if ("/" in raw) raw.substringBefore("/").trim().lowercase() else raw.lowercase()
        val override = overrides[vendor]?.get(role)?.trim().orEmpty()
        if (override.isEmpty()) return raw
        if ("/" !in raw) return override
        val default = roleDefaults(role)[vendor].orEmpty()
        return if (default.isNotEmpty() && compositeModelId(raw) == compositeModelId(default)) override else raw
    }

    private fun compositeFromRoleEntry(vendorKey: String, entry: JsonElement?): String? {
        val modelId = roleModelFromEntry(entry) ?: return null
        val base = "$vendorKey/$modelId"
        val suffix = thinkingSuffixFromRoleEntry(vendorKey, entry)
        return if (suffix != null && suffix.lowercase() !in setOf("none", "off")) "$base@$suffix" else base
    }

    companion object {
        val VALID_VENDOR_KEYS = setOf("openai", "anthropic", "gemini", "mistral", "grok", "deepseek", "local")

        val CONFIGURABLE_VENDOR_ROLES = listOf(
            "extraction", "rag_ranker", "company_research", "letter_plan", "letter_draft", "letter_refine",
            "feedback", "feedback_review", "feedback_context", "autocomplete", "autocomplete_plan", "agentic",
            "paragraph",
        )

        private val ROLE_FALLBACKS = mapOf(
            "letter_plan" to listOf("letter_draft"),
            "letter_refine" to listOf("letter_draft"),
            "feedback_review" to listOf("feedback"),
            "feedback_context" to listOf("feedback"),
            "autocomplete" to listOf("letter_draft"),
            "autocomplete_plan" to listOf("letter_plan", "letter_draft"),
            "agentic" to listOf("letter_draft"),
            "paragraph" to listOf("letter_draft"),
        )

        /** Python `resolve_client_model_role`: the model part when the override targets this vendor. */
        fun resolveClientModelRole(vendor: String, role: ModelRole, overrides: VendorRoleOverrides): RoleRef {
            val vendorKey = vendor.trim().lowercase()
            val override = overrides[vendorKey]?.get(role.value)
            if (override != null && "/" in override) {
                val vendorPart = override.substringBefore("/")
                val modelPart = override.substringAfter("/").trim()
                if (vendorPart.trim().lowercase() == vendorKey && modelPart.isNotEmpty()) {
                    return RoleRef.ModelId(modelPart)
                }
            }
            return RoleRef.Role(role)
        }

        /** Python `split_model_id_and_thinking`. */
        fun splitModelIdAndThinking(modelRole: String): Pair<String, String?> {
            val raw = modelRole.trim()
            if ("@" !in raw) return raw to null
            val modelId = raw.substringBeforeLast("@")
            val suffix = raw.substringAfterLast("@").trim()
            return modelId to suffix.ifEmpty { null }
        }

        /** Python `thinking_config_for_vendor`: UI `@suffix` to the vendor's thinking keys. */
        fun thinkingConfigForVendor(vendorKey: String, suffix: String?): Map<String, JsonElement> {
            val s = suffix?.trim().orEmpty()
            if (s.isEmpty()) return emptyMap()
            return when (vendorKey.lowercase()) {
                "openai", "grok", "deepseek" -> mapOf("reasoning_effort" to JsonPrimitive(s.lowercase()))
                "gemini" -> {
                    val levels = setOf("Minimal", "Low", "Medium", "High")
                    val titled = s.lowercase().replaceFirstChar { it.uppercase() }
                    when {
                        s.lowercase() in setOf("none", "off", "null") ->
                            mapOf("thinking_level" to JsonNull)
                        s in levels -> mapOf("thinking_level" to JsonPrimitive(s))
                        titled in levels -> mapOf("thinking_level" to JsonPrimitive(titled))
                        else -> mapOf("thinking_level" to JsonPrimitive(s))
                    }
                }
                "anthropic" ->
                    if (s.lowercase() in setOf("off", "none", "false")) {
                        mapOf("thinking" to JsonPrimitive(false))
                    } else {
                        mapOf("thinking" to JsonPrimitive(true), "thinking_effort" to JsonPrimitive(s.lowercase()))
                    }
                else -> emptyMap()
            }
        }

        fun normalizeModelKey(modelKey: String, roleDefaults: Map<String, String>): String? {
            val raw = modelKey.trim()
            if (raw.isEmpty()) return null
            if ("/" in raw) {
                val vendorPart = raw.substringBefore("/").trim().lowercase()
                return if (vendorPart in VALID_VENDOR_KEYS) raw else null
            }
            val vendor = raw.lowercase()
            if (vendor !in VALID_VENDOR_KEYS) return null
            return roleDefaults[vendor] ?: vendor
        }

        private fun compositeModelId(composite: String): String {
            val raw = composite.trim()
            if ("/" !in raw) return raw.substringBefore("@")
            return raw.substringAfter("/").substringBefore("@")
        }

        private fun roleModelFromEntry(entry: JsonElement?): String? =
            when (entry) {
                is JsonObject -> (entry["model"] as? JsonPrimitive)?.content?.trim()?.takeIf { it.isNotEmpty() }
                is JsonPrimitive -> entry.asStringOrNull()?.trim()?.takeIf { it.isNotEmpty() }
                else -> null
            }

        private fun thinkingSuffixFromRoleEntry(vendorKey: String, entry: JsonElement?): String? {
            if (entry !is JsonObject) return null
            fun str(key: String): String? = (entry[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
            return when (vendorKey.lowercase()) {
                "openai", "grok", "deepseek" -> {
                    val effort = str("reasoning_effort")?.trim()?.lowercase()
                    if (effort != null && effort !in setOf("", "none")) effort else null
                }
                "gemini" -> {
                    val level = str("thinking_level")?.trim() ?: return null
                    if (level.lowercase() in setOf("none", "null", "off", "")) "none" else level
                }
                "anthropic" -> {
                    val thinking = str("thinking")
                    if (thinking != null && thinking.lowercase() in setOf("false", "off", "none")) return "off"
                    val effort = str("effort")?.takeIf { it.isNotEmpty() } ?: str("thinking_effort")?.takeIf { it.isNotEmpty() }
                    when {
                        effort != null -> effort.trim().lowercase()
                        thinking == "true" -> "medium"
                        else -> null
                    }
                }
                else -> null
            }
        }
    }
}
