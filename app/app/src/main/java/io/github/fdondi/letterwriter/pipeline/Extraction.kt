package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.PyText
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.isPyFalsy
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.PromptCache
import io.github.fdondi.letterwriter.llm.call
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import kotlin.math.abs
import kotlin.math.roundToInt

/** The desktop competence scale defaults (`competenceScales.js`, `job_extraction.py`). */
object CompetenceScale {
    val NEED_SEMANTICS: LinkedHashMap<String, String> = linkedMapOf(
        "critical" to "central to the job",
        "expected" to "necessary, but not specific to the job",
        "nice to have" to "desirable but not required",
        "useful" to "useful but not central",
        "necessary" to "required for the role",
        "marginally useful" to "optional, slight plus",
    )

    /** Level label to the 1..5 rating used for saved competence ratings. */
    val LEVELS: LinkedHashMap<String, Int> = linkedMapOf(
        "Newbie" to 1,
        "Amateur" to 2,
        "Brief experience" to 3,
        "Professional" to 4,
        "Senior professional" to 5,
    )

    val levelLabels: List<String> get() = LEVELS.keys.toList()

    fun defaultLevel(labels: List<String> = levelLabels): String =
        if ("Brief experience" in labels) "Brief experience" else labels[labels.size / 2]

    /** `_level_label_for_rating`. */
    fun levelLabelForRating(rating: Int, labels: List<String> = levelLabels, mapping: Map<String, Int> = LEVELS): String {
        if (labels.isEmpty()) return "Brief experience"
        val target = rating.coerceIn(1, 5)
        if (mapping.isNotEmpty()) {
            var best: String? = null
            var bestDelta = Double.POSITIVE_INFINITY
            for (label in labels) {
                val raw = mapping[label] ?: continue
                val delta = abs(raw.toDouble() - target)
                if (delta < bestDelta) {
                    bestDelta = delta
                    best = label
                }
            }
            if (best != null) return best
        }
        return labels[(target - 1).coerceIn(0, labels.size - 1)]
    }
}

/** `skill_utils.core_skill_name`. */
object SkillNames {
    private val LEADING = listOf(
        "fluent ", "proficient in ", "proficient ", "basic ", "advanced ", "native ", "good ", "strong ",
        "excellent ", "working knowledge of ", "knowledge of ", "experience with ", "experience in ",
    ).sortedByDescending { it.length }
    private val TRAILING = listOf(" language proficiency", " proficiency", " language", " skills").sortedByDescending { it.length }

    private fun collapse(s: String): String = s.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")

    fun core(s: String): String {
        if (s.isBlank()) return ""
        var t = collapse(s)
        while (true) {
            val lower = t.lowercase()
            val lead = LEADING.firstOrNull { lower.startsWith(it) }
            if (lead != null) {
                t = t.substring(lead.length).trim()
                continue
            }
            val trail = TRAILING.firstOrNull { lower.endsWith(it) } ?: break
            t = t.substring(0, t.length - trail.length).trim()
        }
        return collapse(t)
    }

    /** `_normalize_skill`. */
    fun normalize(s: String): String = collapse(s.lowercase())
}

data class CompetenceExtraction(val byCategory: LinkedHashMap<String, List<String>>, val hireProblem: String)

/** Rerank result for one stored document (`RerankDetail`). */
data class RerankRow(
    val score: Int,
    val comment: String,
    val similarities: List<String>,
    val differences: List<String>,
)

data class TopDocumentsResult(
    val topDocs: List<JsonObject>,
    val allScores: Map<String, Int>,
    val allBriefs: Map<String, JsonObject>,
    val scoreDetails: Map<String, JsonObject>,
    val decisionDetail: String,
)

/** Port of `job_extraction.py` and `retrieval.py` used by the intake Extract step. */
class Extraction(private val prompts: Prompts) {

    private val extractionSystem: String get() = prompts.load("extraction/system.txt")

    private fun jobCachePrefix(jobText: String) = PromptCache.combine(extractionSystem, "Job description:\n$jobText")

    /** `extract_job_metadata_no_requirements`. Null [warning] means the reply parsed. */
    suspend fun metadata(jobText: String, client: LlmClient): Pair<JsonObject, String?> {
        val raw = client.call(ModelRole.EXTRACTION, "", listOf(prompts.load("extraction/metadata_prompt.txt")), systemCachePrefix = jobCachePrefix(jobText))
        val data = ModelOutput.loadsObjectOrNull(raw, allowEmbedded = true)
        val warning = if (data.isNullOrEmpty()) "Company/role extraction reply was not a JSON object, so those fields are empty: ${ModelOutput.preview(raw)}" else null
        val d = data ?: JsonObject(emptyMap())
        val out = buildJsonObject {
            put("company_name", cleanMetadata(d["company_name"]))
            put("job_title", cleanMetadata(d["job_title"]))
            put("location", cleanMetadata(d["location"]))
            put("language", cleanMetadata(d["language"]))
            put("salary", cleanMetadata(d["salary"]))
            put("point_of_contact", parsePointOfContact(d["point_of_contact"]) ?: JsonNull)
        }
        return out to warning
    }

    /** `extract_key_competences`. */
    suspend fun competences(
        jobText: String,
        client: LlmClient,
        semantics: LinkedHashMap<String, String> = CompetenceScale.NEED_SEMANTICS,
    ): Pair<CompetenceExtraction, String?> {
        val cats = semantics.keys.toList()
        val example = buildJsonObject {
            put("hire_problem", prompts.load("extraction/competences_example_hire_problem.txt"))
            for (k in cats) put(k, if (k == cats[0]) JsonArray(listOf(JsonPrimitive("C++"), JsonPrimitive("git"))) else JsonArray(emptyList()))
        }
        val parts = cats.mapNotNull { c -> semantics[c]?.trim()?.takeIf { it.isNotEmpty() }?.let { "$c = $it" } }
        val semantic = if (parts.isNotEmpty()) " " + parts.joinToString("; ") + ". " else ""
        val prompt = prompts.render(
            "extraction/competences_prompt.txt",
            "keys" to cats.joinToString(", "),
            "semantic" to semantic,
            "example" to Json.pyDumps(example, itemSeparator = ",", keySeparator = ":"),
        )
        val raw = client.call(ModelRole.EXTRACTION, "", listOf(prompt), systemCachePrefix = jobCachePrefix(jobText))
        val data = ModelOutput.strictObjectOrNull(raw)
        val warning = if (data == null) "Competence extraction reply was not JSON, so no competences were found: ${ModelOutput.preview(raw)}" else null
        val d = data ?: JsonObject(emptyMap())
        val hire = d["hire_problem"]?.let { if (it is JsonNull) "" else it.pyStr().trim() }.orEmpty()
        val out = LinkedHashMap<String, List<String>>()
        for (key in cats) {
            val v = d[key]
            out[key] = if (v is JsonArray) {
                v.map { it.pyStr().trim() }.filter { it.isNotEmpty() }.map { SkillNames.core(it) }.filter { it.isNotEmpty() }
            } else {
                emptyList()
            }
        }
        return CompetenceExtraction(out, hire) to warning
    }

    /** `grade_competence_cv_match`. */
    suspend fun grade(
        competences: List<String>,
        cvText: String,
        client: LlmClient,
        labels: List<String> = CompetenceScale.levelLabels,
    ): Pair<Map<String, String>, String?> {
        if (competences.isEmpty()) return emptyMap<String, String>() to null
        val default = CompetenceScale.defaultLevel(labels)
        val levelList = labels.joinToString(", ")
        val exampleVals = if (labels.size >= 3) listOf(labels.last(), labels[1], labels[labels.size - 2], labels[labels.size - 2]) else List(4) { labels[0] }
        val example = JsonObject(listOf("C++", "German", "English", "git").zip(exampleVals).associate { (k, v) -> k to JsonPrimitive(v) })
        val system = prompts.render("extraction/grade_system.txt", "levels" to levelList)
        val cvExcerpt = PyText.take(cvText, 12000)
        val cacheBlock = PromptCache.combine(system, "========== User CV:\n$cvExcerpt\n==========")
        val prompt = prompts.render(
            "extraction/grade_prompt.txt",
            "competences" to competences.joinToString("\n"),
            "levels" to levelList,
            "example" to Json.pyDumps(example, itemSeparator = ",", keySeparator = ":"),
        )
        val raw = client.call(ModelRole.EXTRACTION, "", listOf(prompt), systemCachePrefix = cacheBlock)
        val data = ModelOutput.strictObjectOrNull(raw)
        val warning = if (data == null) "CV grading reply was not JSON, so every competence got the default level '$default': ${ModelOutput.preview(raw)}" else null
        val d = data ?: JsonObject(emptyMap())
        val labelSet = labels.toSet()
        return competences.associateWith { c ->
            val v = (d[c] as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()
            if (v != null && v in labelSet) v else default
        } to warning
    }

    /** `_process_competences` in `extract_pipeline.py`: (skill, need) pairs, levels from saved ratings, the rest to grade. */
    fun processCompetences(
        byCategory: Map<String, List<String>>,
        ratings: Map<String, Double>,
        needLabels: List<String> = CompetenceScale.NEED_SEMANTICS.keys.toList(),
    ): Triple<List<Pair<String, String>>, Map<String, String>, List<String>> {
        val pairs = ArrayList<Pair<String, String>>()
        val seen = HashSet<String>()
        for (cat in needLabels) for (s in byCategory[cat].orEmpty()) if (s.isNotEmpty() && seen.add(s)) pairs += s to cat
        for ((cat, skills) in byCategory) {
            if (cat in needLabels) continue
            for (s in skills) if (s.isNotEmpty() && seen.add(s)) pairs += s to cat
        }
        val lookup = HashMap<String, Int>()
        for ((k, v) in ratings) {
            if (v in 1.0..5.0) {
                val norm = SkillNames.normalize(k)
                if (norm.isNotEmpty()) lookup[norm] = Math.rint(v).roundToInt()
            }
        }
        val matched = LinkedHashMap<String, String>()
        val unmatched = ArrayList<String>()
        for ((skill, _) in pairs) {
            val r = lookup[SkillNames.normalize(skill)]
            if (r != null) matched[skill] = CompetenceScale.levelLabelForRating(r) else unmatched += skill
        }
        return Triple(pairs, matched, unmatched)
    }

    /** `rerank_documents`: company name to detail, sorted by score (highest first). */
    suspend fun rerank(jobText: String, docs: Map<String, JsonObject>, client: LlmClient): LinkedHashMap<String, RerankRow> {
        val mapping = JsonObject(
            docs.entries.mapIndexed { i, (name, data) ->
                val jt = data["job_text"] ?: throw IllegalStateException("Stored document for '$name' has no job_text")
                i.toString() to buildJsonObject {
                    put("company_name", name)
                    put("job_text", jt)
                }
            }.toMap(LinkedHashMap()),
        )
        val prompt = "Original Job Description:\n" + jobText + "\n\nOther Descriptions (JSON):\n" + Json.pyDumps(mapping, indent = 2)
        var raw = client.call(ModelRole.RAG_RANKER, prompts.load("rag/rerank_system.txt"), listOf(prompt))
        if (raw.startsWith("```json")) raw = raw.substring("```json".length)
        if (raw.endsWith("```")) raw = raw.substring(0, raw.length - 3)
        val table = ModelOutput.strictObjectOrNull(raw.trim())?.get("scores") as? JsonArray
            ?: throw ModelOutputException("Similar-letter ranking reply is not a {\"scores\": [...]} object: ${ModelOutput.preview(raw)}")
        val rows = table.map { el ->
            val o = el.asObjectOrNull() ?: throw ModelOutputException("Ranking row is not an object: $el")
            val name = (o["company_name"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?: throw ModelOutputException("Ranking row has no company_name: $o")
            val comment = (o["comment"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?: throw ModelOutputException("Ranking row for '$name' has no comment")
            name to RerankRow(lenientInt(o["score"], name), comment, points(o["similarities"]), points(o["differences"]))
        }
        val out = LinkedHashMap<String, RerankRow>()
        for ((name, row) in rows.sortedByDescending { it.second.score }) out[name] = row
        return out
    }

    /**
     * `select_top_documents`: rerank, rescore with the decision model, keep the top 3.
     * [rescore] returns company to (score, extra fields) and a status line for the UI.
     */
    suspend fun selectTopDocuments(
        searchResult: List<JsonObject>,
        jobText: String,
        client: LlmClient,
        rescore: suspend (Map<String, Pair<Int, String>>) -> Pair<Map<String, Pair<Int, JsonObject>>, String>,
    ): TopDocumentsResult {
        if (searchResult.isEmpty()) return TopDocumentsResult(emptyList(), emptyMap(), emptyMap(), emptyMap(), "")
        val retrieved = LinkedHashMap<String, JsonObject>()
        for (doc in searchResult) {
            val company = (doc["company_name_original"].strOrNull()?.takeIf { it.isNotEmpty() } ?: doc["company_name"].strOrNull())
            if (!company.isNullOrEmpty()) retrieved[company.trim()] = doc
        }
        val reranked = rerank(jobText, retrieved, client)
        val missing = reranked.keys.filter { it !in retrieved }
        if (missing.isNotEmpty()) {
            throw IllegalStateException(
                "Mismatch between reranked company names and retrieved documents. Missing from retrieved_docs: $missing. " +
                    "Expected company names: ${retrieved.keys.sorted()}. Got from reranking: ${reranked.keys.sorted()}.",
            )
        }
        val (rescored, detail) = rescore(reranked.mapValues { (name, r) -> r.score to (retrieved[name]?.get("job_text").pyStrOrEmpty()) })
        val scored = reranked.entries.map { (name, r) ->
            val (score, extra) = rescored[name] ?: (r.score to JsonObject(emptyMap()))
            Triple(name, r, score to extra)
        }.sortedByDescending { it.third.first }

        val topDocs = scored.take(3).map { (name, r, s) ->
            val doc = retrieved.getValue(name)
            JsonObject(
                linkedMapOf<String, JsonElement>(
                    "id" to (doc["id"] ?: JsonPrimitive("")),
                    "company_name" to JsonPrimitive(name),
                    "score" to JsonPrimitive(s.first),
                    "similarities" to JsonArray(r.similarities.map(::JsonPrimitive)),
                    "differences" to JsonArray(r.differences.map(::JsonPrimitive)),
                    "comment" to JsonPrimitive(r.comment),
                    "job_text" to JsonPrimitive(doc["job_text"].pyStrOrEmpty()),
                    "letter_text" to JsonPrimitive(doc["letter_text"].pyStrOrEmpty()),
                ) + s.second,
            )
        }
        return TopDocumentsResult(
            topDocs = topDocs,
            allScores = scored.associate { it.first to it.third.first },
            allBriefs = scored.associate { (name, r, _) ->
                name to buildJsonObject {
                    put("similarities", JsonArray(r.similarities.map(::JsonPrimitive)))
                    put("differences", JsonArray(r.differences.map(::JsonPrimitive)))
                    put("comment", r.comment)
                }
            },
            scoreDetails = scored.associate { it.first to it.third.second },
            decisionDetail = detail,
        )
    }

    companion object {
        private val STRIP_FIELDS = setOf("vector", "user_id", "blocks", "ai_letters", "negative_letter_text", "notes")

        /** `sanitize_search_results` (timestamps are already ISO strings in [StoredDocument]). */
        fun sanitize(docs: List<JsonObject>): List<JsonObject> = docs.map { doc ->
            val clean = doc.filterKeys { it !in STRIP_FIELDS }.toMutableMap()
            if ("company_name_original" in clean) {
                val original = clean["company_name_original"]
                clean["company_name"] = if (original.isTruthy()) original!! else (clean["company_name"] ?: JsonPrimitive(""))
            }
            JsonObject(clean)
        }

        /** `_clean_metadata_val`. */
        fun cleanMetadata(v: JsonElement?): String = when {
            v == null || v is JsonNull -> ""
            v is JsonArray -> v.map { it.pyStr().trim() }.filter { it.isNotEmpty() }.joinToString(", ")
            v is JsonPrimitive && !v.isString && v.content != "true" && v.content != "false" -> v.content
            else -> v.pyStr().trim()
        }

        /** `_parse_point_of_contact`. */
        fun parsePointOfContact(v: JsonElement?): JsonObject? {
            val o = v as? JsonObject ?: return null
            if (o.isEmpty()) return null
            val poc = buildJsonObject {
                put("name", cleanMetadata(o["name"]))
                put("role", cleanMetadata(o["role"]))
                put("contact_details", cleanMetadata(o["contact_details"]))
                put("notes", cleanMetadata(o["notes"]))
            }
            if (poc.getStr("name").isEmpty() && poc.getStr("contact_details").isEmpty()) return null
            return poc
        }

        /** `_normalize_points`: up to 4 non-empty strings. */
        private fun points(v: JsonElement?): List<String> =
            (v as? JsonArray).orEmpty().map { it.pyStr().trim() }.filter { it.isNotEmpty() }.take(4)

        /** Pydantic lax `int`: integral numbers or numeric strings. */
        private fun lenientInt(v: JsonElement?, name: String): Int {
            val p = v as? JsonPrimitive ?: throw ModelOutputException("Ranking row for '$name' has no score")
            val d = (if (p.isString) p.content.trim().toDoubleOrNull() else p.doubleOrNull)
                ?: throw ModelOutputException("Ranking score for '$name' is not a number: $p")
            if (d != Math.floor(d)) throw ModelOutputException("Ranking score for '$name' is not an integer: $p")
            return d.toInt()
        }

        private fun JsonElement?.strOrNull(): String? = (this as? JsonPrimitive)?.takeIf { it.isString }?.content

        private fun JsonElement?.pyStrOrEmpty(): String = if (this.isTruthy()) this.pyStr() else ""

        private fun JsonElement?.isTruthy(): Boolean = !isPyFalsy()
    }
}
