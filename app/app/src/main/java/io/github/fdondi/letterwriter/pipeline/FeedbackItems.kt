package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.isPyFalsy
import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.decision.DecisionJudge
import io.github.fdondi.letterwriter.decision.DecisionKeys
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import java.util.UUID

/** Feedback item shapes and normalization (`feedback_checks.py`). Items stay JSON so they round-trip to Firestore unchanged. */
object FeedbackItems {
    /** Phased feedback categories, in display and prompt order. */
    val CATEGORIES = listOf("instruction", "accuracy", "precision", "company_fit", "goal_fit", "user_fit", "human")

    val MATERIAL_SOURCES = setOf("CV", "EXAMPLE", "BACKGROUND_RESEARCH", "LETTER")
    const val USER_SOURCE = "USER"
    val ALL_SOURCES = MATERIAL_SOURCES + USER_SOURCE
    val STATUSES = setOf("NOT_NEEDED", "SUFFICIENT", "INPUT_NEEDED")
    private val TYPES = setOf("ALREADY_GOOD", "PLEASE_FIX")

    private val KEPT_VERDICTS = setOf(
        DecisionKeys.VERDICT_VALID,
        DecisionKeys.VERDICT_INVALID,
        DecisionKeys.VERDICT_UNSCORED,
        DecisionKeys.VERDICT_UNCALIBRATED,
    )

    fun isDecisionHidden(item: JsonObject): Boolean = DecisionJudge.isHidden(item)

    /** Python truthiness of a JSON value, as `bool(x)`. */
    fun pyBool(v: JsonElement?): Boolean = !v.isPyFalsy()

    fun contextItems(item: JsonObject): List<JsonElement> =
        ((item["context_field"] as? JsonObject)?.get("items") as? JsonArray).orEmpty()

    private fun userFitHasExampleLetters(topDocs: List<JsonObject>?): Boolean =
        topDocs.orEmpty().any { it.textOrEmpty("letter_text").isNotBlank() }

    private fun humanHasRevisionExamples(topDocs: List<JsonObject>?): Boolean =
        topDocs.orEmpty().any { ex -> pyBool(ex["letter_text"]) && (ex["ai_letters"] as? JsonArray)?.isNotEmpty() == true }

    /** `allowed_feedback_context_sources_for_category`. */
    fun allowedSources(category: String, topDocs: List<JsonObject>? = null): Set<String> =
        when (category.trim().lowercase()) {
            "instruction" -> setOf("LETTER", "BACKGROUND_RESEARCH")
            "accuracy" -> setOf("CV", "LETTER")
            "precision", "company_fit", "goal_fit" -> setOf("BACKGROUND_RESEARCH", "LETTER")
            "user_fit" -> if (userFitHasExampleLetters(topDocs)) setOf("CV", "LETTER", "EXAMPLE") else setOf("CV", "LETTER")
            "human" -> if (humanHasRevisionExamples(topDocs)) setOf("EXAMPLE", "LETTER") else setOf("LETTER")
            else -> MATERIAL_SOURCES
        }

    /** `legacy_context_string_default_source_for_category`. */
    fun legacySource(category: String, topDocs: List<JsonObject>? = null): String =
        when (category.trim().lowercase()) {
            "instruction" -> "BACKGROUND_RESEARCH"
            "accuracy" -> "CV"
            "precision", "company_fit", "goal_fit" -> "BACKGROUND_RESEARCH"
            "user_fit" -> if (userFitHasExampleLetters(topDocs)) "EXAMPLE" else "CV"
            "human" -> if (humanHasRevisionExamples(topDocs)) "EXAMPLE" else "LETTER"
            else -> "CV"
        }

    fun materialAllowed(allowed: Set<String>): Set<String> = (allowed intersect MATERIAL_SOURCES).ifEmpty { MATERIAL_SOURCES }

    /** `normalize_parsed_feedback_items`: first-pass model output. Throws on more than 2 INPUT_NEEDED rows (the caller retries). */
    fun normalizeParsed(data: JsonElement, allowedSources: Set<String>, legacySource: String = "CV"): List<JsonObject> {
        val raw: List<JsonElement> = when {
            data is JsonObject && data["items"] is JsonArray -> data["items"] as JsonArray
            data is JsonArray -> data
            else -> emptyList()
        }
        val allowed = materialAllowed(allowedSources)
        val out = ArrayList<JsonObject>()
        var inputNeeded = 0
        for (el in raw) {
            val it = el as? JsonObject ?: continue
            val obs = it.getStr("observation").trim()
            val typ = it.getStr("type").trim().uppercase()
            if (typ !in TYPES || obs.isEmpty()) continue
            var status = it.textOrEmpty("status").trim().uppercase()
            if (status !in STATUSES) status = "NOT_NEEDED"
            var ctx = ArrayList<JsonObject>()
            for (r in contextItems(it)) {
                if (r is JsonPrimitive && r.isString) {
                    val t = r.content.trim()
                    if (t.isNotEmpty() && legacySource in allowed) ctx += contextRow(t, legacySource)
                    continue
                }
                val ro = r as? JsonObject ?: continue
                val t = ro.textOrEmpty("text").trim()
                val src = ro.textOrEmpty("source").trim().uppercase()
                if (t.isEmpty() || src !in allowed) continue
                ctx += contextRow(t, src)
            }
            if (status == "NOT_NEEDED") ctx = ArrayList()
            else if (status == "SUFFICIENT" && ctx.isEmpty()) status = "NOT_NEEDED"
            if (status == "INPUT_NEEDED") {
                inputNeeded++
                if (inputNeeded > 2) throw ModelOutputException("Too many INPUT_NEEDED items (hard max 2)")
            }
            val userInstructions = if (status == "INPUT_NEEDED") it.textOrEmpty("user_instructions").trim() else ""
            out += buildJsonObject {
                put("id", UUID.randomUUID().toString())
                put("observation", obs)
                put("type", typ)
                put("status", status)
                put("context_field", buildJsonObject { put("items", JsonArray(ctx)) })
                put("user_context", "")
                put("user_instructions", userInstructions)
                put("quote", it.textOrEmpty("quote").trim())
                put("matched_text", "")
            }
        }
        return out
    }

    /** `_normalize_missing_context_items_payload` (request-context replies). */
    fun normalizeMissingContext(data: JsonElement, allowedSources: Set<String>, legacySource: String): List<JsonObject> {
        val raw = ((data as? JsonObject)?.get("items") as? JsonArray) ?: return emptyList()
        val allowed = materialAllowed(allowedSources)
        val out = ArrayList<JsonObject>()
        for (r in raw) {
            if (r is JsonPrimitive && r.isString) {
                val t = r.content.trim()
                if (t.isNotEmpty() && legacySource in allowed) out += contextRow(t, legacySource)
                continue
            }
            val ro = r as? JsonObject ?: continue
            val t = ro.textOrEmpty("text").trim()
            val src = ro.textOrEmpty("source").trim().uppercase()
            if (t.isEmpty() || src !in allowed) continue
            out += contextRow(t, src)
        }
        return out
    }

    private fun contextRow(text: String, source: String) = buildJsonObject {
        put("text", text)
        put("source", source)
    }

    /** `normalize_feedback_value` for one category (stored or user-edited items). */
    fun normalizeValue(value: JsonElement?, category: String, topDocs: List<JsonObject>? = null): List<JsonObject> {
        if (value == null || value is JsonNull) return emptyList()
        if (value is JsonPrimitive && value.isString) return legacyStringToItems(value.content)
        val list = value as? JsonArray ?: return emptyList()
        val allowed = allowedSources(category, topDocs)
        val legacy = legacySource(category, topDocs)
        val out = ArrayList<JsonObject>()
        for (el in list) {
            val it = el as? JsonObject ?: continue
            val obs = it.getStr("observation").trim()
            val typ = it.getStr("type").trim().uppercase()
            if (typ !in TYPES || obs.isEmpty()) continue
            val id = it.textOrEmpty("id").trim().ifEmpty { UUID.randomUUID().toString() }
            var status = it.textOrEmpty("status").trim().uppercase()
            if (status !in STATUSES) status = "NOT_NEEDED"
            var ctx = ArrayList<JsonObject>()
            for (r in contextItems(it)) {
                if (r is JsonPrimitive && r.isString) {
                    val t = r.content.trim()
                    if (t.isNotEmpty() && legacy in allowed) ctx += contextRow(t, legacy)
                    continue
                }
                val ro = r as? JsonObject ?: continue
                val src = ro.textOrEmpty("source").trim().uppercase()
                if (src !in ALL_SOURCES) continue
                if (src != USER_SOURCE && src !in allowed) continue
                val isUser = src == USER_SOURCE
                val t = if (isUser) ro.textOrEmpty("text") else ro.textOrEmpty("text").trim()
                if (!isUser && t.isEmpty()) continue
                ctx += buildJsonObject {
                    put("text", t)
                    put("source", src)
                    if (isUser) {
                        val p = ro["persist_to_cv"]
                        put("persist_to_cv", if (p == null || p is JsonNull) true else pyBool(p))
                    }
                }
            }
            if (status == "NOT_NEEDED") ctx = ArrayList()
            else if (status == "SUFFICIENT" && ctx.isEmpty()) status = "NOT_NEEDED"
            val needsInput = status == "INPUT_NEEDED"
            val persistCv = it["persist_user_context_to_cv"].let { p -> if (p == null || p is JsonNull) true else pyBool(p) }
            val persistAgents = it["persist_user_context_for_agents"].let { p -> if (p == null || p is JsonNull) persistCv else pyBool(p) }
            val row = linkedMapOf<String, JsonElement>(
                "id" to JsonPrimitive(id),
                "observation" to JsonPrimitive(obs),
                "type" to JsonPrimitive(typ),
                "status" to JsonPrimitive(status),
                "context_field" to buildJsonObject { put("items", JsonArray(ctx)) },
                "user_context" to JsonPrimitive(if (needsInput) it.textOrEmpty("user_context").trim() else ""),
                "user_instructions" to JsonPrimitive(if (needsInput) it.textOrEmpty("user_instructions").trim() else ""),
                "input_declined" to JsonPrimitive(needsInput && pyBool(it["input_declined"])),
                "persist_user_context_to_cv" to JsonPrimitive(persistCv),
                "persist_user_context_for_agents" to JsonPrimitive(persistAgents),
                "quote" to JsonPrimitive(it.textOrEmpty("quote").trim()),
                "matched_text" to JsonPrimitive(it.textOrEmpty("matched_text").trim()),
            )
            val start = intOrNull(it["span_start"])
            val end = intOrNull(it["span_end"])
            if (it["span_start"] != null && it["span_start"] !is JsonNull && start != null && end != null) {
                row["span_start"] = JsonPrimitive(start)
                row["span_end"] = JsonPrimitive(end)
            }
            it.textOrEmpty("draft_vendor").trim().takeIf { s -> s.isNotEmpty() }?.let { dv -> row["draft_vendor"] = JsonPrimitive(dv) }
            copyDecisionFields(it, row)
            it.textOrEmpty("duplicate_group_id").trim().takeIf { s -> s.isNotEmpty() }?.let { dg -> row["duplicate_group_id"] = JsonPrimitive(dg) }
            it.textOrEmpty("input_cluster_key").trim().takeIf { s -> s.isNotEmpty() }?.let { ck -> row["input_cluster_key"] = JsonPrimitive(ck) }
            out += JsonObject(row)
        }
        return out
    }

    /** `normalize_feedback_map`: every category present, each a normalized list. */
    fun normalizeMap(feedback: JsonObject?, topDocs: List<JsonObject>? = null): LinkedHashMap<String, List<JsonObject>> {
        val out = LinkedHashMap<String, List<JsonObject>>()
        for (k in CATEGORIES) out[k] = normalizeValue(feedback?.get(k), k, topDocs)
        return out
    }

    fun toJson(map: Map<String, List<JsonObject>>): JsonObject = JsonObject(map.mapValues { JsonArray(it.value) })

    /** `_copy_laya_feedback_fields`, under the app's `decision_*` names. */
    private fun copyDecisionFields(src: JsonObject, row: MutableMap<String, JsonElement>) {
        val verdict = src.textOrEmpty(DecisionKeys.VERDICT).trim().lowercase()
        if (verdict in KEPT_VERDICTS) row[DecisionKeys.VERDICT] = JsonPrimitive(verdict)
        for (key in listOf(DecisionKeys.VALID_PROBABILITY, DecisionKeys.CONFIDENCE)) {
            val p = src[key] as? JsonPrimitive ?: continue
            if (p.isString || p.booleanOrNull != null) continue
            p.doubleOrNull?.let { row[key] = JsonPrimitive(it) }
        }
        for (key in listOf(DecisionKeys.MODEL, DecisionKeys.DEVICE, DecisionKeys.ERROR)) {
            src.textOrEmpty(key).trim().takeIf { it.isNotEmpty() }?.let { row[key] = JsonPrimitive(it) }
        }
        if ((src[DecisionKeys.RESTORED] as? JsonPrimitive)?.booleanOrNull == true) row[DecisionKeys.RESTORED] = JsonPrimitive(true)
    }

    private fun intOrNull(v: JsonElement?): Int? {
        val p = v as? JsonPrimitive ?: return null
        return if (p.isString) p.content.trim().toIntOrNull() else p.doubleOrNull?.toInt()
    }

    /** `_legacy_feedback_string_to_items`. */
    private fun legacyStringToItems(value: String): List<JsonObject> {
        val t = value.trim()
        if (t.isEmpty()) return emptyList()
        val u = t.uppercase()
        if (u.endsWith("NO COMMENT") || u.endsWith("SKIP")) return emptyList()
        val obs = if (u.endsWith("PLEASE FIX")) t.dropLast("PLEASE FIX".length).trimEnd() else t
        if (obs.isEmpty()) return emptyList()
        return listOf(
            buildJsonObject {
                put("id", UUID.randomUUID().toString())
                put("observation", obs)
                put("type", "PLEASE_FIX")
            },
        )
    }
}
