package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.PyText
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.data.CompaniesRepository
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelOverrides
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.llm.RoleRef
import io.github.fdondi.letterwriter.llm.VendorRoleOverrides
import io.github.fdondi.letterwriter.llm.ref
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.time.Instant
import java.time.OffsetDateTime
import java.time.temporal.ChronoUnit

data class CompanyResearchResult(
    /** Model id to `{report, updated_at}` or `{error}`, as stored in `companies/{id}.reports`. */
    val results: JsonObject,
    /** "cache", "similar" or "new". */
    val source: String,
    val resolvedName: String,
    val warnings: List<String>,
)

/**
 * Port of `research.py` (`perform_company_research`, `perform_poc_research`).
 *
 * The desktop also reranks similar letters once per research model and stores
 * the picks with the report, then strips them on save; the phone skips that call
 * because the intake rerank already chose the example letters.
 */
class Research(
    private val prompts: Prompts,
    private val companies: CompaniesRepository,
    private val clientFor: (ModelVendor) -> LlmClient,
    private val overrides: () -> VendorRoleOverrides,
    private val modelOverrides: ModelOverrides,
) {
    suspend fun company(
        companyName: String,
        models: List<String>,
        jobText: String,
        additionalCompanyInfo: String,
        searchInstructions: String,
    ): CompanyResearchResult {
        val warnings = ArrayList<String>()
        if (companyName.isEmpty()) return CompanyResearchResult(JsonObject(emptyMap()), "new", companyName, warnings)

        var cached = companies.get(companyName)
        var matchedName = companyName
        var foundViaSearch = false
        var previousContext = ""
        if (cached == null) {
            val candidates = try {
                companies.searchSimilar(companyName, limit = 5)
            } catch (e: Exception) {
                warnings += "Similar-company lookup failed, so only an exact cache hit could be reused: ${e.message}"
                emptyList()
            }
            val chosen = candidates.firstOrNull { looksLikeSameCompany(companyName, it["company_name"].asStringOrNull().orEmpty()) }
            if (chosen != null) {
                matchedName = chosen["company_name"].asStringOrNull()?.takeIf { it.isNotEmpty() } ?: companyName
                cached = chosen
                foundViaSearch = true
                val docId = chosen["id"].asStringOrNull()
                if (!docId.isNullOrEmpty()) {
                    try {
                        companies.saveAlias(companyName, docId, matchedName).warning?.let { warnings += it }
                    } catch (e: Exception) {
                        warnings += "Could not save company alias '$companyName' → '$docId': ${e.message}"
                    }
                }
            }
        }

        if (cached != null) {
            val updatedAt = parseInstant(cached["updated_at"].asStringOrNull())
            if (updatedAt != null) {
                val cutoff = Instant.now().minus(180, ChronoUnit.DAYS)
                val reports = cached["reports"].asObjectOrNull() ?: JsonObject(emptyMap())
                val covers = reports.keys.containsAll(models.toSet())
                if (updatedAt.isAfter(cutoff) && covers) {
                    return CompanyResearchResult(
                        JsonObject(reports.filterKeys { it in models }.let { CompaniesRepository.stripTopDocs(JsonObject(it)) as JsonObject }),
                        if (foundViaSearch) "similar" else "cache",
                        matchedName,
                        warnings,
                    )
                }
                previousContext = reports.values.mapNotNull { it.asObjectOrNull() }
                    .maxByOrNull { PyText.length(it["report"].asStringOrNull().orEmpty()) }
                    ?.get("report").asStringOrNull().orEmpty()
            }
        }

        val snippet = PyText.take(jobText.trim(), 500)
        var query = "From a job applicant's perspective (work culture, daily tasks, career prospects, hiring stability — " +
            "not investor metrics like AUM or net profit): research $companyName."
        if (snippet.isNotEmpty()) query += " Job context: $snippet"
        val webContext = webSearch(query, searchInstructions, warnings)

        var combined = additionalCompanyInfo
        if (previousContext.isNotEmpty()) combined += "\n\n[Previous Research Context (older than 6 months)]:\n$previousContext"
        if (webContext.isNotEmpty()) combined += "\n\n[Web Search Findings]:\n$webContext"

        val results = coroutineScope {
            models.map { m ->
                async {
                    m to try {
                        val (vendor, role) = parseModel(m)
                        val report = companyReport(companyName, jobText, clientFor(vendor), combined, role, searchInstructions)
                        buildJsonObject {
                            put("report", report?.let(::JsonPrimitive) ?: JsonNull)
                            put("updated_at", Instant.now().toString())
                        }
                    } catch (e: Exception) {
                        buildJsonObject { put("error", e.message ?: e::class.simpleName.orEmpty()) }
                    }
                }
            }.awaitAll()
        }
        val resultObj = JsonObject(results.toMap(LinkedHashMap()))
        companies.save(companyName, buildJsonObject { put("reports", resultObj) }).warning?.let { warnings += it }
        return CompanyResearchResult(resultObj, "new", companyName, warnings)
    }

    /** `perform_poc_research`. Returns model id to `{report, updated_at}` or `{error}`. */
    suspend fun pointOfContact(
        pocName: String,
        models: List<String>,
        companyName: String,
        jobText: String,
    ): Pair<JsonObject, List<String>> {
        val warnings = ArrayList<String>()
        if (pocName.isEmpty() || companyName.isEmpty()) return JsonObject(emptyMap()) to warnings
        val cached = companies.getPoc(companyName, pocName)
        var previousContext = ""
        if (cached != null) {
            val updatedAt = parseInstant(cached["updated_at"].asStringOrNull())
            if (updatedAt != null) {
                val reports = cached["reports"].asObjectOrNull() ?: JsonObject(emptyMap())
                val covers = reports.keys.containsAll(models.toSet())
                if (updatedAt.isAfter(Instant.now().minus(180, ChronoUnit.DAYS)) && covers) {
                    return JsonObject(reports.filterKeys { it in models }) to warnings
                }
                previousContext = reports.values.mapNotNull { it.asObjectOrNull() }
                    .maxByOrNull { PyText.length(it["report"].asStringOrNull().orEmpty()) }
                    ?.get("report").asStringOrNull().orEmpty()
            }
        }
        var query = "Research $pocName at $companyName"
        if (jobText.isNotEmpty()) query += "\nContext from job offer: ${PyText.take(jobText, 200)}..."
        val webContext = webSearch(query, "", warnings)
        var combined = ""
        if (previousContext.isNotEmpty()) combined += "\n\n[Previous Research Context (older than 6 months)]:\n$previousContext"
        if (webContext.isNotEmpty()) combined += "\n\n[Web Search Findings]:\n$webContext"

        val results = coroutineScope {
            models.map { m ->
                async {
                    m to try {
                        val (vendor, role) = parseModel(m)
                        var prompt = "Research the following person: $pocName at $companyName"
                        if (jobText.isNotEmpty()) prompt += "\n\nContext from job offer:\n${PyText.take(jobText, 500)}..."
                        if (combined.isNotEmpty()) prompt += "\n\nResearch Findings:\n$combined"
                        prompt += "\n\nProvide a professional summary about this person, their role, and any public information relevant for a job application."
                        val report = clientFor(vendor).call(role, "You are a professional research assistant.", listOf(prompt), search = false)
                        buildJsonObject {
                            put("report", report)
                            put("updated_at", Instant.now().toString())
                        }
                    } catch (e: Exception) {
                        buildJsonObject { put("error", e.message ?: e::class.simpleName.orEmpty()) }
                    }
                }
            }.awaitAll()
        }
        val resultObj = JsonObject(results.toMap(LinkedHashMap()))
        companies.savePoc(companyName, pocName, resultObj)
        return resultObj to warnings
    }

    /** `company_research` with search=False (the web findings are already in [additionalInfo]). */
    private suspend fun companyReport(
        companyName: String,
        jobText: String,
        client: LlmClient,
        additionalInfo: String,
        role: RoleRef,
        searchInstructions: String,
    ): String? {
        val system = searchInstructions.trim().ifEmpty { prompts.load("research/default_system.txt") }
        val companyPrompt = if (companyName.isNotEmpty()) {
            prompts.render("research/company_prompt.txt", "company_name" to companyName, "job_excerpt" to PyText.take(jobText, 500))
        } else {
            ""
        }
        val userContext = if (additionalInfo.isNotBlank()) prompts.render("research/additional_company_info.txt", "info" to additionalInfo) else ""
        val prompt = companyPrompt + userContext
        if (prompt.isEmpty()) return null
        return client.call(role, system, listOf(prompt), search = false)
    }

    /** `perform_web_search`. The desktop returns "" silently on failure; here the reason is kept as a warning. */
    private suspend fun webSearch(query: String, searchInstructions: String, warnings: MutableList<String>): String {
        val system = searchInstructions.trim().ifEmpty {
            "You are researching a company to help someone write a cover letter. " +
                "Focus on work culture, likely work tasks, and career prospects — not investor metrics. " +
                "Do NOT include any links, only plain text."
        }
        return try {
            clientFor(ModelVendor.OPENAI).call(RoleRef.ModelId(WEB_SEARCH_MODEL), system, listOf(query), search = true)
        } catch (e: Exception) {
            warnings += "Web search ($WEB_SEARCH_MODEL) failed, so the report has no fresh web findings: ${e.message}"
            ""
        }
    }

    /** `_parse_model_str` + `_model_for_company_research`. */
    private fun parseModel(modelStr: String): Pair<ModelVendor, RoleRef> {
        val vendorKey = modelStr.substringBefore("/")
        val vendor = ModelVendor.fromKey(vendorKey)
            ?: throw IllegalArgumentException(
                "Unknown vendor '$vendorKey' in model string '$modelStr'. Valid vendors: ${ModelVendor.entries.map { it.key }}",
            )
        if ("/" !in modelStr) return vendor to ModelRole.COMPANY_RESEARCH.ref()
        val modelId = modelStr.substringAfter("/")
        val resolved = modelOverrides.applyStoredRoleOverride("${vendor.key}/$modelId", "company_research", overrides())
        return vendor to RoleRef.ModelId(if ("/" in resolved) resolved.substringAfter("/") else modelId)
    }

    companion object {
        const val WEB_SEARCH_MODEL = "gpt-5-search-api"

        fun parseInstant(raw: String?): Instant? {
            val s = raw?.trim().orEmpty()
            if (s.isEmpty()) return null
            return runCatching { Instant.parse(s) }.getOrNull()
                ?: runCatching { OffsetDateTime.parse(s).toInstant() }.getOrNull()
        }

        private fun normCompany(s: String) = s.trim().lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")

        /** `_looks_like_same_company`. */
        fun looksLikeSameCompany(query: String, candidate: String): Boolean {
            val q = normCompany(query)
            val c = normCompany(candidate)
            if (q.isEmpty() || c.isEmpty()) return false
            if (q == c) return true
            if (PyText.length(q) >= 5 && (q in c || c in q)) return true
            if (SequenceMatcher.ratio(q, c) >= 0.86) return true
            val qt = q.replace("-", " ").split(" ").filter { it.isNotEmpty() }.toSet()
            val ct = c.replace("-", " ").split(" ").filter { it.isNotEmpty() }.toSet()
            if (qt.isNotEmpty() && ct.isNotEmpty()) {
                val jaccard = (qt intersect ct).size.toDouble() / (qt union ct).size
                if (jaccard >= 0.8) return true
            }
            return false
        }
    }
}

/** Python `difflib.SequenceMatcher(a, b).ratio()` with the default autojunk heuristic, over code points. */
object SequenceMatcher {
    fun ratio(aStr: String, bStr: String): Double {
        val a = aStr.codePoints().toArray()
        val b = bStr.codePoints().toArray()
        val total = a.size + b.size
        if (total == 0) return 1.0
        return 2.0 * matches(a, b) / total
    }

    private fun matches(a: IntArray, b: IntArray): Int {
        val n = b.size
        val b2j = HashMap<Int, MutableList<Int>>()
        b.forEachIndexed { j, ch -> b2j.getOrPut(ch) { ArrayList() }.add(j) }
        if (n >= 200) {
            val ntest = n / 100 + 1
            b2j.entries.removeAll { it.value.size > ntest }
        }
        var count = 0
        val queue = ArrayDeque<IntArray>()
        queue.add(intArrayOf(0, a.size, 0, n))
        while (queue.isNotEmpty()) {
            val (alo, ahi, blo, bhi) = queue.removeLast()
            val (i, j, k) = longestMatch(a, b, b2j, alo, ahi, blo, bhi)
            if (k > 0) {
                count += k
                if (alo < i && blo < j) queue.add(intArrayOf(alo, i, blo, j))
                if (i + k < ahi && j + k < bhi) queue.add(intArrayOf(i + k, ahi, j + k, bhi))
            }
        }
        return count
    }

    private fun longestMatch(a: IntArray, b: IntArray, b2j: Map<Int, List<Int>>, alo: Int, ahi: Int, blo: Int, bhi: Int): Triple<Int, Int, Int> {
        var besti = alo
        var bestj = blo
        var bestsize = 0
        var j2len = HashMap<Int, Int>()
        for (i in alo until ahi) {
            val newj2len = HashMap<Int, Int>()
            for (j in b2j[a[i]].orEmpty()) {
                if (j < blo) continue
                if (j >= bhi) break
                val k = (j2len[j - 1] ?: 0) + 1
                newj2len[j] = k
                if (k > bestsize) {
                    besti = i - k + 1
                    bestj = j - k + 1
                    bestsize = k
                }
            }
            j2len = newj2len
        }
        // No isjunk function, so nothing is "junk"; popular elements only skip the b2j index and still extend matches.
        while (besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1]) {
            besti--
            bestj--
            bestsize++
        }
        while (besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] == b[bestj + bestsize]) {
            bestsize++
        }
        return Triple(besti, bestj, bestsize)
    }
}
