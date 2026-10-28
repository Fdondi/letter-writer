package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.PyText
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.PromptCache
import io.github.fdondi.letterwriter.llm.call
import io.github.fdondi.letterwriter.llm.toHex
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.util.Collections
import java.util.UUID

/** One INPUT_NEEDED row sent to stage 4. */
data class InputRow(val id: String, val vendor: String, val category: String, val observation: String, val userInstructions: String)

/**
 * Port of `feedback_review.py`. The desktop fails open silently when a stage
 * reply does not parse; the phone fails open too (nothing is dropped) but
 * reports it in [warnings].
 */
class FeedbackReview(private val prompts: Prompts, private val checks: FeedbackChecks, private val defaultStyle: () -> String) {

    /** Appended from the per-category stages, which run concurrently. */
    val warnings: MutableList<String> = Collections.synchronizedList(ArrayList())

    /** `review_feedback_for_vendor`: stages 1+2 per category, then 4, then 3. */
    suspend fun reviewForVendor(
        client: LlmClient,
        draftLetter: String,
        feedback: Map<String, List<JsonObject>>,
        inputs: LetterInputs,
        vendor: String,
        knownWeaknesses: JsonArray,
    ): LinkedHashMap<String, List<JsonObject>> {
        val fb = FeedbackItems.normalizeMap(FeedbackItems.toJson(feedback), inputs.topDocs)
        val flat = fb.flatMap { (cat, items) -> items.filter { it.textOrEmpty("id").isNotEmpty() }.map { cat to it } }
        if (flat.isEmpty()) return fb

        val ctx = LinkedHashMap<String, String>()
        val byCat = LinkedHashMap<String, MutableList<Pair<String, String>>>()
        for ((cat, it) in flat) {
            val obs = it.getStr("observation").trim()
            if (obs.isEmpty()) continue
            ctx.getOrPut(cat) { justificationContext(cat, draftLetter, inputs, knownWeaknesses) }
            byCat.getOrPut(cat) { ArrayList() }.add(it.getStr("id") to obs)
        }
        val keep = HashMap<String, Boolean>()
        if (byCat.isNotEmpty()) {
            val tasks = byCat.keys.map { cat ->
                Triple<String, String?, suspend () -> Map<String, Boolean>>(cat, ctx[cat].orEmpty()) {
                    stage12(client, cat, byCat.getValue(cat), ctx.getValue(cat))
                }
            }
            PromptCache.runCacheGroupedTasks(tasks, maxParallelGroups = 7).values.forEach { keep.putAll(it) }
        }
        val kept = flat.filter { (_, it) -> it.getStr("observation").trim().isNotEmpty() && (keep[it.getStr("id")] ?: true) }
        val rebuilt = LinkedHashMap<String, MutableList<JsonObject>>()
        for (k in FeedbackItems.CATEGORIES) rebuilt[k] = ArrayList()
        for ((cat, it) in kept) rebuilt.getOrPut(cat) { ArrayList() }.add(it)

        val rows = FeedbackItems.CATEGORIES.flatMap { cat ->
            rebuilt[cat].orEmpty().filter { isInputNeeded(it) }.map {
                InputRow(it.getStr("id"), vendor, cat, it.getStr("observation"), it.getStr("user_instructions"))
            }
        }
        val idToCluster = if (rows.isNotEmpty()) stage4(client, rows) else emptyMap()
        for (cat in FeedbackItems.CATEGORIES) {
            rebuilt[cat] = rebuilt[cat].orEmpty().map { it ->
                val m = it.toMutableMap()
                if (!isInputNeeded(it)) {
                    m.remove("input_cluster_key")
                } else {
                    val ck = idToCluster[it.textOrEmpty("id")]
                    if (ck != null) m["input_cluster_key"] = JsonPrimitive(ck) else m.remove("input_cluster_key")
                }
                JsonObject(m)
            }.toMutableList()
        }

        val stage3Items = FeedbackItems.CATEGORIES.flatMap { cat ->
            rebuilt[cat].orEmpty().filter { !isInputNeeded(it) }.map { Triple(it.getStr("id"), cat, it.getStr("observation")) }
        }
        val dup = if (stage3Items.size >= 2) stage3(client, stage3Items) else emptyMap()
        for (cat in FeedbackItems.CATEGORIES) {
            rebuilt[cat] = rebuilt[cat].orEmpty().map { it ->
                if (isInputNeeded(it)) return@map it
                val m = it.toMutableMap()
                val gid = dup[it.textOrEmpty("id")]
                if (gid != null) m["duplicate_group_id"] = JsonPrimitive(gid) else m.remove("duplicate_group_id")
                JsonObject(m)
            }.toMutableList()
        }
        val out = LinkedHashMap<String, List<JsonObject>>()
        for ((k, v) in rebuilt) out[k] = v
        return applyInputClusterGroups(out)
    }

    /**
     * `merge_input_clusters_across_session_vendors`: one stage-4 call over every
     * vendor's INPUT_NEEDED rows so the same question gets one cluster key everywhere.
     */
    suspend fun mergeInputClustersAcrossVendors(
        client: LlmClient,
        feedbackByVendor: Map<String, Map<String, List<JsonObject>>>,
        topDocsByVendor: Map<String, List<JsonObject>>,
    ): Map<String, LinkedHashMap<String, List<JsonObject>>> {
        val rows = ArrayList<InputRow>()
        for ((vendor, fbRaw) in feedbackByVendor) {
            val fb = FeedbackItems.normalizeMap(FeedbackItems.toJson(fbRaw), topDocsByVendor[vendor])
            for (cat in FeedbackItems.CATEGORIES) {
                for (it in fb[cat].orEmpty()) {
                    if (!isInputNeeded(it)) continue
                    rows += InputRow("$vendor::$cat::${it["id"].pyStr()}", vendor, cat, it.getStr("observation"), it.getStr("user_instructions"))
                }
            }
        }
        if (rows.size < 2) return feedbackByVendor.mapValues { (_, fb) -> LinkedHashMap(fb) }
        val mapping = stage4(client, rows)
        return feedbackByVendor.mapValues { (vendor, fb) ->
            val updated = LinkedHashMap<String, List<JsonObject>>()
            for ((cat, items) in fb) {
                updated[cat] = items.map { it ->
                    if (!isInputNeeded(it)) return@map it
                    val ck = mapping["$vendor::$cat::${it["id"].pyStr()}"] ?: return@map it
                    JsonObject(it + ("input_cluster_key" to JsonPrimitive(ck)))
                }
            }
            applyInputClusterGroups(updated)
        }
    }

    /** `_build_justification_context`. */
    internal fun justificationContext(category: String, letter: String, inputs: LetterInputs, known: JsonArray): String {
        val si = inputs.styleInstructions.ifEmpty { defaultStyle() }
        val add = inputs.additionalUserInfo.trim()
        val kw = checks.knownWeaknessesBlock(known)
        val companyJob = "========== Company Report:\n${inputs.companyReport}\n==========\n\n========== Job Offer:\n${inputs.jobText}\n==========\n\n" +
            "========== Cover Letter:\n$letter\n==========\n"
        return when (category) {
            "instruction" -> "========== Style Instructions:\n$si\n==========\n\n========== Cover Letter:\n$letter\n==========\n$kw"
            "accuracy" -> {
                val extra = if (add.isNotEmpty()) "\n\nUser additional info (may explain facts not in CV):\n$add\n" else ""
                "========== User CV:\n${inputs.cvText}\n==========\n\n========== Cover Letter:\n$letter\n==========\n$extra$kw"
            }
            "precision", "company_fit" -> companyJob + kw
            "goal_fit" -> {
                val hp = inputs.hireProblem.trim()
                val prefix = if (hp.isNotEmpty()) "========== Hire goal / problem this role solves (structured extraction):\n$hp\n==========\n\n" else ""
                prefix + companyJob + kw
            }
            "user_fit" -> {
                val examples = referenceExamples(inputs.topDocs).ifBlank { "(No reference letters available.)" }
                val cv = inputs.cvText.trim().ifEmpty { "(No CV text was provided in this session.)" }
                val extra = if (add.isNotEmpty()) "\n\n========== User's additional info (relevant but not fully captured in CV):\n$add\n==========\n" else ""
                "========== Reference Examples:\n$examples\n==========\n\n========== User CV:\n$cv\n==========\n$extra\n========== Cover Letter:\n$letter\n==========\n$kw"
            }
            "human" -> "========== Reference Examples:\n${referenceExamples(inputs.topDocs)}\n==========\n\n========== Cover Letter:\n$letter\n==========\n$kw"
            else -> "========== Cover Letter:\n$letter\n==========\n$kw"
        }
    }

    private fun referenceExamples(topDocs: List<JsonObject>): String =
        topDocs.withIndex().filter { (_, ex) -> FeedbackItems.pyBool(ex["letter_text"]) }.joinToString("\n\n") { (i, ex) ->
            "---- Example #${i + 1} - ${ex.getStr("company_name")} ----\nCover Letter:\n${ex.getStr("letter_text")}\n\n"
        }

    /** `_stage12_batch`: keep/drop per id; ids the model omits get one retry, then default to keep. */
    internal suspend fun stage12(client: LlmClient, category: String, items: List<Pair<String, String>>, context: String): Map<String, Boolean> {
        if (items.isEmpty()) return emptyMap()
        val prefix = "========== Context the checker saw ==========\n$context"
        val system = prompts.render(
            "review/stage12_system.txt",
            "category" to category,
            "known_weaknesses_rules" to prompts.load("feedback/known_weaknesses_rules.txt"),
        )
        val key = PromptCache.cacheKeyForPrefix(prefix, "feedback_review:$category")
        suspend fun ask(batch: List<Pair<String, String>>): Map<String, Boolean> {
            val prompt = "Critiques:\n" + batch.joinToString("\n") { (id, obs) -> "id=$id: ${PyText.take(obs.trim(), 1200)}" }
            val raw = client.call(ModelRole.FEEDBACK_REVIEW, system, listOf(prompt), systemCachePrefix = prefix, promptCacheKey = key)
            val data = ModelOutput.loadsObjectOrNull(raw, allowEmbedded = false)
            if (data == null) warnings += "Review of $category comments did not return JSON; those comments were kept unfiltered."
            val out = HashMap<String, Boolean>()
            for (r in (data?.get("results") as? JsonArray).orEmpty()) {
                val o = r as? JsonObject ?: continue
                out[o["id"]?.pyStr() ?: ""] = o["keep"]?.let { FeedbackItems.pyBool(it) } ?: true
            }
            return out
        }
        val out = HashMap(ask(items))
        val missing = items.filter { it.first !in out }
        if (missing.isNotEmpty()) out.putAll(ask(missing))
        return out
    }

    /** `_stage3_duplicate_groups` (non-INPUT_NEEDED only). Input is (id, category, observation). */
    internal suspend fun stage3(client: LlmClient, items: List<Triple<String, String, String>>): Map<String, String> {
        if (items.size < 2) return emptyMap()
        val prompt = "Items:\n" + items.joinToString("\n") { (id, cat, obs) -> "- id=$id category=$cat :: ${PyText.take(obs, 1200)}" }
        val raw = client.call(ModelRole.FEEDBACK_REVIEW, prompts.load("review/stage3_system.txt"), listOf(prompt))
        val data = ModelOutput.loadsObjectOrNull(raw, allowEmbedded = false)
        val groups = data?.get("groups") as? JsonArray
        if (groups == null) {
            warnings += "Duplicate grouping did not return JSON groups; duplicates are not linked."
            return emptyMap()
        }
        val out = HashMap<String, String>()
        for (g in groups) {
            val ids = (g as? JsonArray ?: continue).map { it.pyStr().trim() }.filter { it.isNotEmpty() }
            if (g.size < 2 || ids.size < 2) continue
            val gid = UUID.randomUUID().toString().take(12)
            ids.forEach { out[it] = gid }
        }
        return out
    }

    /** `_stage4_input_clusters`: id to slug. */
    internal suspend fun stage4(client: LlmClient, rows: List<InputRow>): Map<String, String> {
        if (rows.isEmpty()) return emptyMap()
        val composite = rows.any { "::" in it.id }
        val hint = prompts.load(if (composite) "review/stage4_id_hint_composite.txt" else "review/stage4_id_hint_plain.txt")
        val system = prompts.render("review/stage4_system.txt", "id_hint" to hint)
        val prompt = "Rows:\n" + rows.joinToString("\n") {
            "- id=${it.id} vendor=${it.vendor} category=${it.category} :: obs=${PyText.take(it.observation, 400)} :: hint=${PyText.take(it.userInstructions, 200)}"
        }
        val raw = client.call(ModelRole.FEEDBACK_REVIEW, system, listOf(prompt))
        val data = ModelOutput.loadsObjectOrNull(raw, allowEmbedded = false)
        val clusters = data?.get("clusters") as? JsonArray
        if (clusters == null) {
            warnings += "Grouping of questions for you did not return JSON clusters; identical questions are not linked."
            return emptyMap()
        }
        val out = HashMap<String, String>()
        for (c in clusters) {
            val o = c as? JsonObject ?: continue
            val key = o.textOrEmpty("key").trim()
            val ids = o["ids"] as? JsonArray
            if (key.isEmpty() || ids == null) continue
            val slug = key.lowercase().replace(Regex("[^a-z0-9_]+"), "_").trim('_').take(64).ifEmpty { "cluster" }
            for (i in ids) {
                val sid = i.pyStr().trim()
                if (sid.isNotEmpty()) out[sid] = slug
            }
        }
        return out
    }

    companion object {
        fun isInputNeeded(item: JsonObject) = item.getStr("status").uppercase() == "INPUT_NEEDED"

        /** `_input_cluster_duplicate_group_id`. */
        fun clusterGroupId(clusterKey: String): String =
            "inp_" + MessageDigest.getInstance("SHA-256").digest(clusterKey.trim().toByteArray(Charsets.UTF_8)).toHex().take(12)

        /** `apply_input_cluster_duplicate_groups`. */
        fun applyInputClusterGroups(feedback: Map<String, List<JsonObject>>): LinkedHashMap<String, List<JsonObject>> {
            val out = LinkedHashMap<String, List<JsonObject>>()
            for ((cat, items) in feedback) {
                out[cat] = if (cat !in FeedbackItems.CATEGORIES) items else items.map { it ->
                    if (!isInputNeeded(it)) return@map it
                    val m = it.toMutableMap<String, JsonElement>()
                    val ck = it.textOrEmpty("input_cluster_key").trim()
                    if (ck.isNotEmpty()) {
                        m["duplicate_group_id"] = JsonPrimitive(clusterGroupId(ck))
                    } else if (it["duplicate_group_id"]?.pyStr()?.startsWith("inp_") == true) {
                        m.remove("duplicate_group_id")
                    }
                    JsonObject(m)
                }
            }
            return out
        }
    }
}
