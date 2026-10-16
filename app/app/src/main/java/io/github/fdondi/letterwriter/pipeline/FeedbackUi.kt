package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.decision.DecisionKeys
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

/**
 * Port of `feedbackItemUtils.js` and `useFeedbackItemApprovals.js`: how the review
 * screen normalizes items, what counts as approved, and the feedback rows saved to
 * the profile. Decision fields use the app's `decision_*` names.
 */
object FeedbackUi {
    const val PLEASE_FIX = "PLEASE_FIX"
    const val ALREADY_GOOD = "ALREADY_GOOD"
    val CONTEXT_SOURCES = listOf("CV", "EXAMPLE", "BACKGROUND_RESEARCH", "LETTER")
    const val CONTEXT_USER_SOURCE = "USER"

    private fun JsonElement?.js(): String = when (this) {
        null, is JsonNull -> ""
        else -> pyStr()
    }

    private fun JsonObject.flag(key: String): Boolean? = this[key].asBooleanOrNull()

    private fun normalizeContextSource(raw: JsonElement?): String {
        val s = raw.js().trim().uppercase()
        if (s == CONTEXT_USER_SOURCE) return CONTEXT_USER_SOURCE
        return if (s in CONTEXT_SOURCES) s else "CV"
    }

    private fun contextRow(text: String, source: String, from: JsonObject?): JsonObject = buildJsonObject {
        put("text", text)
        put("source", source)
        if (source == CONTEXT_USER_SOURCE) {
            val persistCv = from?.flag("persist_to_cv") != false
            val persistAgents = from?.get("persist_for_agents")?.let { from.flag("persist_for_agents") != false } ?: persistCv
            put("persist_to_cv", persistCv)
            put("persist_for_agents", persistAgents)
        }
    }

    private fun normalizeContextItems(raw: JsonElement?): List<JsonObject> {
        val arr = raw as? JsonArray ?: return emptyList()
        val out = ArrayList<JsonObject>()
        for (it in arr) {
            if (it is JsonPrimitive && it.isString) {
                val text = it.content.trimEnd()
                if (text.isNotBlank()) out += contextRow(text, "CV", null)
                continue
            }
            val o = it as? JsonObject ?: continue
            out += contextRow(o["text"].js().trimEnd(), normalizeContextSource(o["source"]), o)
        }
        return out
    }

    /** `normalizeCategoryItems`. Ids fall back to `{category}-{index}` like the desktop. */
    fun normalizeCategoryItems(raw: JsonElement?, categoryKey: String): List<JsonObject> {
        if (raw == null || raw is JsonNull) return emptyList()
        if (raw is JsonPrimitive && raw.isString) return legacyString(raw.content, categoryKey)
        val list = raw as? JsonArray ?: return emptyList()
        return list.mapIndexedNotNull { idx, el ->
            val it = el.asObjectOrNull() ?: return@mapIndexedNotNull null
            val observation = it["observation"].js().trim()
            val typ = it["type"].js().uppercase()
            if (typ != ALREADY_GOOD && typ != PLEASE_FIX) return@mapIndexedNotNull null
            if (typ == ALREADY_GOOD && observation.isEmpty()) return@mapIndexedNotNull null
            val id = it["id"].js().trim().ifEmpty { if (categoryKey.isNotEmpty()) "$categoryKey-$idx" else UUID.randomUUID().toString() }
            var status = it["status"].js().uppercase().trim().let { s ->
                if (s == "NOT_NEEDED" || s == "SUFFICIENT" || s == "INPUT_NEEDED") s else "NOT_NEEDED"
            }
            val cfItems = normalizeContextItems((it["context_field"] as? JsonObject)?.get("items"))
            if (status == "NOT_NEEDED" && cfItems.isNotEmpty()) status = "SUFFICIENT"
            val contextItems = if (status == "NOT_NEEDED") emptyList() else cfItems
            if (status == "SUFFICIENT" && contextItems.isEmpty()) status = "NOT_NEEDED"
            val inputNeeded = status == "INPUT_NEEDED"
            val persistCv = it.flag("persist_user_context_to_cv") != false
            val persistAgents = if ("persist_user_context_for_agents" in it) it.flag("persist_user_context_for_agents") != false else persistCv
            buildJsonObject {
                put("id", id)
                put("observation", observation)
                put("type", typ)
                put("status", status)
                put("context_field", buildJsonObject { put("items", JsonArray(contextItems)) })
                put("user_context", if (inputNeeded) it["user_context"].js() else "")
                put("user_instructions", if (inputNeeded) it["user_instructions"].js().trim() else "")
                put("persist_user_context_to_cv", persistCv)
                put("persist_user_context_for_agents", persistAgents)
                put("input_declined", inputNeeded && it.flag("input_declined") == true)
                put("quote", it["quote"].js().trim())
                put("matched_text", it["matched_text"].js().trim())
                for ((k, v) in decisionFields(it)) put(k, v)
                val start = it["span_start"].asDoubleOrNull()
                val end = it["span_end"].asDoubleOrNull()
                if (start != null && end != null) {
                    put("span_start", start.toInt())
                    put("span_end", end.toInt())
                }
                it["draft_vendor"].js().trim().takeIf { v -> v.isNotEmpty() }?.let { v -> put("draft_vendor", v) }
                // Kept so linked approvals work on the normalized list (the desktop reads them from the raw list).
                for (k in listOf("duplicate_group_id", "input_cluster_key")) {
                    it[k].js().trim().takeIf { v -> v.isNotEmpty() }?.let { v -> put(k, v) }
                }
            }
        }
    }

    private fun legacyString(raw: String, categoryKey: String): List<JsonObject> {
        val t = raw.trim()
        if (t.isEmpty()) return emptyList()
        val u = t.uppercase()
        if (u.endsWith("NO COMMENT") || u.endsWith("SKIP")) return emptyList()
        val obs = if (u.endsWith("PLEASE FIX")) t.dropLast("PLEASE FIX".length).trim() else t
        if (obs.isEmpty()) return emptyList()
        val id = if (categoryKey.isNotEmpty()) "$categoryKey-legacy-0" else UUID.randomUUID().toString()
        return listOf(buildJsonObject {
            put("id", id)
            put("observation", obs)
            put("type", PLEASE_FIX)
        })
    }

    /** `layaFieldsFromItem`, plus the phone-only `uncalibrated` verdict. */
    private fun decisionFields(it: JsonObject): Map<String, JsonElement> {
        val out = LinkedHashMap<String, JsonElement>()
        val verdict = it[DecisionKeys.VERDICT].js().lowercase()
        if (verdict in setOf(DecisionKeys.VERDICT_VALID, DecisionKeys.VERDICT_INVALID, DecisionKeys.VERDICT_UNSCORED, DecisionKeys.VERDICT_UNCALIBRATED)) {
            out[DecisionKeys.VERDICT] = JsonPrimitive(verdict)
        }
        for (k in listOf(DecisionKeys.VALID_PROBABILITY, DecisionKeys.CONFIDENCE)) {
            val v = (it[k] as? JsonPrimitive)?.takeIf { p -> !p.isString }?.content?.toDoubleOrNull()
            if (v != null && v.isFinite()) out[k] = JsonPrimitive(v)
        }
        for (k in listOf(DecisionKeys.MODEL, DecisionKeys.DEVICE, DecisionKeys.ERROR)) {
            val v = it[k].js().trim()
            if (v.isNotEmpty()) out[k] = JsonPrimitive(v)
        }
        if (it.flag(DecisionKeys.RESTORED) == true) out[DecisionKeys.RESTORED] = JsonPrimitive(true)
        return out
    }

    fun isHidden(it: JsonObject): Boolean =
        it.flag(DecisionKeys.RESTORED) != true && it[DecisionKeys.VERDICT].js().lowercase() == DecisionKeys.VERDICT_INVALID

    /** `withLayaRestored`: editing or approving a hidden comment puts it back into the letter. */
    fun withRestored(it: JsonObject): JsonObject =
        if (!isHidden(it)) it else JsonObject(it + (DecisionKeys.RESTORED to JsonPrimitive(true)))

    fun pleaseFixItems(items: List<JsonObject>): List<JsonObject> = items.filter { it["type"].js() == PLEASE_FIX && !isHidden(it) }

    fun itemIsApproved(it: JsonObject, approvals: Map<String, Boolean>): Boolean {
        if (it["type"].js() != PLEASE_FIX) return true
        if (it["status"].js().uppercase() == "INPUT_NEEDED") {
            if (it.flag("input_declined") == true) return true
            return it["user_context"].js().trim().isNotEmpty()
        }
        return approvals[it["id"].js()] == true
    }

    fun categoryAllItemsApproved(items: List<JsonObject>, approvals: Map<String, Boolean>): Boolean =
        items.filter { !isHidden(it) }.all { itemIsApproved(it, approvals) }

    /** Ids sharing the item's `duplicate_group_id` or `input_cluster_key`: one approval covers all of them. */
    fun linkedIds(item: JsonObject, allItems: List<JsonObject>): Set<String> {
        val ids = linkedSetOf(item["id"].js())
        val dg = item["duplicate_group_id"].js()
        val ick = item["input_cluster_key"].js()
        for (row in allItems) {
            if (dg.isNotEmpty() && row["duplicate_group_id"].js() == dg) ids += row["id"].js()
            if (ick.isNotEmpty() && row["input_cluster_key"].js() == ick) ids += row["id"].js()
        }
        return ids
    }

    /** `extractFeedbackEntryToExtraInfo`. */
    fun extraInfoRow(category: String, it: JsonObject): JsonObject? {
        val persist = it.flag("persist_user_context_to_cv") != false
        val ucRaw = if (persist) it["user_context"].js() else ""
        if (ucRaw.isBlank()) return null
        return buildJsonObject {
            put("id", it["id"].js())
            put("source", "feedback")
            put("category", category)
            put("observation", "")
            put("user_context", ucRaw)
            put("user_instructions", if (persist) it["user_instructions"].js().trim() else "")
            put("context_lines", JsonArray(emptyList()))
            put("manual_text", "")
        }
    }

    /** `extractFeedbackEntryToAgentContext`. */
    fun agentContextRow(category: String, it: JsonObject): JsonObject? {
        val persist = if ("persist_user_context_for_agents" in it) it.flag("persist_user_context_for_agents") != false
        else it.flag("persist_user_context_to_cv") != false
        val ucRaw = if (persist) it["user_context"].js() else ""
        if (ucRaw.isBlank()) return null
        return buildJsonObject {
            put("id", it["id"].js())
            put("source", "feedback")
            put("category", category)
            put("user_context", ucRaw)
            put("user_instructions", if (persist) it["user_instructions"].js().trim() else "")
        }
    }

    /** `mergeExtraInfoFromFeedback` / `mergeAgentContextFromFeedback`. */
    fun mergeRows(
        existing: List<JsonObject>,
        itemsByCategory: Map<String, List<JsonObject>>,
        extract: (String, JsonObject) -> JsonObject?,
    ): List<JsonObject> {
        val map = LinkedHashMap<String, JsonObject>()
        for (e in existing) map[e["id"].js()] = e
        for ((category, items) in itemsByCategory) {
            for (it in items) {
                val id = it["id"].js()
                val row = extract(category, it)
                if (row != null) {
                    map[id] = row
                } else if (map[id]?.get("source").js() == "feedback") {
                    map.remove(id)
                }
            }
        }
        return map.values.toList()
    }
}
