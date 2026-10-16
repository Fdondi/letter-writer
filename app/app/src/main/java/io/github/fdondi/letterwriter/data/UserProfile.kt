package io.github.fdondi.letterwriter.data

import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.llm.Catalogs
import io.github.fdondi.letterwriter.llm.ModelOverrides
import io.github.fdondi.letterwriter.llm.VendorRoleOverrides
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/** `personal_data/{sub}` as JSON, with the getters of `personal_data_sections.py`. */
class UserProfile(val sub: String, val data: JsonObject) {

    fun unwrap(key: String): JsonElement? {
        val raw = data[key] ?: return null
        return if (raw is JsonObject && "value" in raw) raw["value"] else raw
    }

    val cvRevisions: List<JsonObject> get() = data["cv_revisions"].asArrayOrNull().orEmpty().mapNotNull { it.asObjectOrNull() }

    /** Latest revision by `created_at` (ISO strings sort like Python datetimes). */
    val baseCv: String
        get() = cvRevisions.maxByOrNull { it["created_at"].asStringOrNull().orEmpty() }?.textOrEmpty("content").orEmpty()

    val extraInfo: List<JsonObject>
        get() = data["extra_info"].asArrayOrNull().orEmpty().mapNotNull { it.asObjectOrNull() }.filter { !it.textOrEmpty("id").isEmpty() }

    val agentFeedbackContext: List<JsonObject>
        get() = data["agent_feedback_context"].asArrayOrNull().orEmpty().mapNotNull { it.asObjectOrNull() }
            .filter { it.textOrEmpty("id").isNotEmpty() }

    /** Python `cv_text_with_extra_info`. */
    fun cvWithExtraInfo(): String {
        val base = baseCv
        val appendix = formatExtraInfoForCvAppendix(extraInfo)
        if (base.isBlank() && appendix.isNotEmpty()) return appendix.trim()
        if (appendix.isEmpty()) return base
        return base.trimEnd() + appendix
    }

    /** `models` = vendors selected by default for the vendor flow. */
    val defaultVendors: List<String>
        get() = unwrap("models").asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull() }

    val extractionVendor: String
        get() = unwrap("extraction_vendor").asStringOrNull()?.trim()?.lowercase()
            ?.takeIf { it in ModelOverrides.VALID_VENDOR_KEYS } ?: "openai"

    fun roleOverrides(overrides: ModelOverrides): VendorRoleOverrides {
        for (field in listOf("vendor_role_model_overrides", "phase_model_overrides")) {
            val stored = unwrap(field) as? JsonObject ?: continue
            if (stored.isNotEmpty()) return overrides.normalize(stored)
        }
        return emptyMap()
    }

    /**
     * Python `get_background_models`. Returns the models plus ids dropped because the
     * phone cannot run them (unknown vendor, no web search, or the desktop-only `local` vendor).
     */
    fun backgroundModels(catalogs: Catalogs): Pair<List<String>, List<String>> {
        val stored = unwrap("background_models").asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull() }
        if (stored.isEmpty()) return DEFAULT_BACKGROUND_MODELS to emptyList()
        val searchable = catalogs.allModels(searchOnly = true).map { it.composite }.toSet()
        val (kept, dropped) = stored.partition { baseCompositeModelId(it) in searchable }
        return kept.ifEmpty { DEFAULT_BACKGROUND_MODELS } to dropped
    }

    val competenceRatings: Map<String, Double>
        get() {
            var obj = unwrap("competences") as? JsonObject ?: JsonObject(emptyMap())
            (obj["ratings"] as? JsonObject)?.let { obj = it }
            if (obj.isEmpty()) obj = data["competence_ratings"] as? JsonObject ?: JsonObject(emptyMap())
            return obj.mapNotNull { (k, v) -> v.asDoubleOrNull()?.let { k to it } }.toMap()
        }

    fun styleInstructions(): String = firstInstruction("style", "style_instructions")

    fun structureInstructions(): String = firstInstruction("structure", "structure_instructions")

    fun searchInstructions(): String = unwrap("search_instructions").asStringOrNull().orEmpty()

    fun instructionBaselineHash(kind: InstructionKind): String =
        kind.firestoreKeys.firstNotNullOfOrNull { key ->
            (data[key] as? JsonObject)?.get("default_baseline_hash").asStringOrNull()?.trim()?.takeIf { it.isNotEmpty() }
        }.orEmpty()

    fun instructionBaselineText(kind: InstructionKind): String =
        kind.firestoreKeys.firstNotNullOfOrNull { key ->
            (data[key] as? JsonObject)?.get("default_baseline_text").asStringOrNull()?.trim()?.takeIf { it.isNotEmpty() }
        }.orEmpty()

    fun customInstruction(kind: InstructionKind): String =
        when (kind) {
            InstructionKind.STYLE -> styleInstructions()
            InstructionKind.STRUCTURE -> structureInstructions()
            InstructionKind.SEARCH -> searchInstructions()
        }

    private fun firstInstruction(vararg keys: String): String {
        for (key in keys) {
            val out = unwrap(key).asStringOrNull()
            if (!out.isNullOrBlank()) return out
        }
        return ""
    }

    companion object {
        val DEFAULT_BACKGROUND_MODELS = listOf("gemini/gemini-3-flash-preview")

        fun baseCompositeModelId(modelId: String): String {
            val mid = modelId.trim()
            if ("/" !in mid) return mid
            val vendor = mid.substringBefore("/")
            val rest = mid.substringAfter("/")
            return "$vendor/${if ("@" in rest) rest.substringBeforeLast("@") else rest}"
        }

        private fun hasBody(it: JsonObject): Boolean {
            val src = it.textOrEmpty("source").trim().lowercase()
            if (src == "feedback") return it.textOrEmpty("user_context").isNotBlank()
            if (it.textOrEmpty("manual_text").isNotBlank()) return true
            if (it.textOrEmpty("user_context").isNotBlank()) return true
            if (it.textOrEmpty("user_instructions").isNotBlank()) return true
            if (it.textOrEmpty("observation").isNotBlank()) return true
            return it["context_lines"].asArrayOrNull().orEmpty().any { l -> l.pyStr().isNotBlank() }
        }

        /** Python `format_extra_info_for_cv_appendix` (same markdown, byte for byte). */
        fun formatExtraInfoForCvAppendix(extraInfo: List<JsonObject>): String {
            val nonempty = extraInfo.filter(::hasBody)
            if (nonempty.isEmpty()) return ""
            val parts = StringBuilder()
            parts.append("\n\n---\n\n## Additional context (saved notes)\n\n")
            parts.append(
                "The following notes were saved from your feedback or your CV settings. " +
                    "Treat them as part of your background, alongside the CV above.\n\n",
            )
            nonempty.forEachIndexed { index, it ->
                val i = index + 1
                val src = it.textOrEmpty("source").trim().lowercase()
                val cat = it.textOrEmpty("category").trim()
                val obs = it.textOrEmpty("observation").trim()
                val uc = it.textOrEmpty("user_context").trim()
                val ui = it.textOrEmpty("user_instructions").trim()
                val ctxLines = it["context_lines"].asArrayOrNull().orEmpty().map { l -> l.pyStr().trim() }.filter { l -> l.isNotEmpty() }
                val manual = it.textOrEmpty("manual_text").trim()

                parts.append("### Note $i" + (if (cat.isNotEmpty()) " ($cat)" else "") + "\n\n")
                if (src == "feedback" && uc.isNotEmpty()) {
                    parts.append("**Q:** $uc\n\n")
                    if (ui.isNotEmpty()) parts.append("**A:** $ui\n\n")
                    return@forEachIndexed
                }
                if (src.isNotEmpty()) {
                    val more = obs.isNotEmpty() || uc.isNotEmpty() || ui.isNotEmpty() || ctxLines.isNotEmpty() || manual.isNotEmpty()
                    parts.append("*Source:* $src" + if (more) "  \n" else "\n")
                }
                if (obs.isNotEmpty()) parts.append("*Related feedback:* $obs\n\n")
                if (ui.isNotEmpty()) parts.append("*Instructions:* $ui\n\n")
                if (ctxLines.isNotEmpty()) {
                    parts.append("*Context lines:*\n")
                    ctxLines.forEach { ln -> parts.append("- $ln\n") }
                    parts.append("\n")
                }
                if (uc.isNotEmpty() && src != "feedback") parts.append("*Your context:*\n\n$uc\n\n")
                if (manual.isNotEmpty()) parts.append("$manual\n\n")
            }
            return parts.toString().trimEnd() + "\n"
        }

        /** Python `format_agent_feedback_context_for_prompt`. */
        fun formatAgentFeedbackContextForPrompt(rows: List<JsonObject>): String {
            val nonempty = rows.filter { it.textOrEmpty("user_context").isNotBlank() }
            if (nonempty.isEmpty()) return ""
            val parts = ArrayList<String>()
            nonempty.forEachIndexed { index, it ->
                val cat = it.textOrEmpty("category").trim()
                val uc = it.textOrEmpty("user_context").trim()
                val ui = it.textOrEmpty("user_instructions").trim()
                parts.add("Note ${index + 1}" + (if (cat.isNotEmpty()) " ($cat)" else "") + "\n")
                parts.add("Q: $uc\n")
                if (ui.isNotEmpty()) parts.add("A: $ui\n")
                parts.add("")
            }
            return parts.joinToString("\n").trimEnd()
        }
    }
}

enum class InstructionKind(val key: String, val defaultFile: String, val firestoreKeys: List<String>) {
    STYLE("style", "defaults/style_instructions.txt", listOf("style", "style_instructions")),
    STRUCTURE("structure", "defaults/structure_instructions.txt", listOf("structure", "structure_instructions")),
    SEARCH("search", "defaults/search_instructions.txt", listOf("search_instructions")),
}
