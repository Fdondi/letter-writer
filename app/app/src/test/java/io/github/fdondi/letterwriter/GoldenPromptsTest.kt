package io.github.fdondi.letterwriter

import io.github.fdondi.letterwriter.core.FileSharedAssets
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.data.CompaniesRepository
import io.github.fdondi.letterwriter.data.Embeddings
import io.github.fdondi.letterwriter.data.LanguageSettings
import io.github.fdondi.letterwriter.decision.DecisionJudge
import io.github.fdondi.letterwriter.decision.StoredFieldNames
import io.github.fdondi.letterwriter.llm.Catalogs
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelOverrides
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.llm.RoleRef
import io.github.fdondi.letterwriter.llm.ref
import io.github.fdondi.letterwriter.pipeline.Extraction
import io.github.fdondi.letterwriter.pipeline.FeedbackChecks
import io.github.fdondi.letterwriter.pipeline.FeedbackItems
import io.github.fdondi.letterwriter.pipeline.FeedbackReview
import io.github.fdondi.letterwriter.pipeline.InputRow
import io.github.fdondi.letterwriter.pipeline.LetterGeneration
import io.github.fdondi.letterwriter.pipeline.LetterInputs
import io.github.fdondi.letterwriter.pipeline.Research
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Renders the cases of `letter_writer/prompts/golden/expected.json` (written by
 * `scripts/prompts/capture_golden.py` from the desktop code) with the phone's
 * phase code and requires identical model calls.
 */
class GoldenPromptsTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val assets = FileSharedAssets(repoRoot)
    private val prompts = Prompts(assets)
    private val golden = repoRoot.resolve("letter_writer/prompts/golden")
    private val inp = Json.parse(golden.resolve("inputs.json").readText()).jsonObject
    private val expected = Json.parse(golden.resolve("expected.json").readText()).jsonObject

    private val languages = LanguageSettings(prompts)
    private val generation = LetterGeneration(prompts)
    private val extraction = Extraction(prompts)
    private val checks = FeedbackChecks(prompts, generation::defaultStyle)
    private val review = FeedbackReview(prompts, checks, generation::defaultStyle)

    /** Cases the phone does not reproduce on purpose; each must say why. */
    private val notReplayed = mapOf(
        "research_custom" to "desktop helper called with search=True and a point of contact; neither app's research flow does that (see research_flow)",
        "research_default" to "same helper with search=True; the research flow always passes search=False",
        "paragraph_regenerate" to "paragraph flow is web-only for now",
        "paragraph_regenerate_defaults" to "paragraph flow is web-only for now",
        "paragraph_continue" to "paragraph flow is web-only for now",
        "paragraph_continue_empty" to "paragraph flow is web-only for now",
    )

    private class Recording(private val reply: String) : LlmClient {
        override val vendor = ModelVendor.OPENAI
        val calls = ArrayList<JsonObject>()

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
            synchronized(calls) {
                calls += buildJsonObject {
                    put("role", when (role) {
                        is RoleRef.Role -> role.role.value
                        is RoleRef.ModelId -> role.id
                    })
                    put("system", system)
                    put("user_messages", JsonArray(userMessages.map(::JsonPrimitive)))
                    put("search", search)
                    put("response_format", responseFormat ?: JsonNull)
                    put("cache_prefix", cachePrefix?.let(::JsonPrimitive) ?: JsonNull)
                    put("system_cache_prefix", systemCachePrefix?.let(::JsonPrimitive) ?: JsonNull)
                    put("prompt_cache_key", promptCacheKey?.let(::JsonPrimitive) ?: JsonNull)
                }
            }
            return reply
        }
    }

    private fun s(key: String) = inp[key]!!.jsonPrimitive.content
    private fun objs(el: JsonElement?) = el!!.jsonArray.map { it.jsonObject }

    private val cv = s("cv_text")
    private val job = s("job_text")
    private val report = s("company_report")
    private val letter = s("letter")
    private val kw = inp["known_weaknesses"]!!.jsonArray
    private val docs = objs(inp["top_docs"])
    private val add = s("additional_user_info")
    private val hire = s("hire_problem")
    private val userData = inp["user_data"]!!.jsonObject
    private val langPrefix = languages.systemPrefix(userData, "German")

    private fun inputs(
        cvText: String = cv,
        jobText: String = job,
        companyReport: String = report,
        topDocs: List<JsonObject> = docs,
        additional: String = add,
        hireProblem: String = hire,
        languagePrefix: String = "",
        style: String = "",
        structure: String = "",
    ) = LetterInputs(cvText, jobText, companyReport, topDocs, additional, hireProblem, languagePrefix, style, structure)

    private val mismatches = ArrayList<String>()
    private val checked = LinkedHashSet<String>()

    private fun compareResult(case: String, actual: String) {
        checked += case
        val want = expected[case]!!.jsonObject["result"]!!.jsonPrimitive.content
        if (want != actual) mismatches += "$case: result differs\n  desktop: ${want.take(400)}\n  phone:   ${actual.take(400)}"
    }

    private fun compareCalls(case: String, reply: String, ignoreFields: Set<String> = emptySet(), result: String? = null, block: suspend (LlmClient) -> Any?) {
        checked += case
        val rec = Recording(reply)
        val out = runBlocking { block(rec) }
        val exp = expected[case]!!.jsonObject
        val want = exp["calls"]!!.jsonArray.map { it.jsonObject }
        if (want.size != rec.calls.size) {
            mismatches += "$case: desktop made ${want.size} call(s), phone made ${rec.calls.size}"
            return
        }
        for ((i, pair) in want.zip(rec.calls).withIndex()) {
            val (w, a) = pair
            for (field in w.keys - ignoreFields) {
                if (w[field] != a[field]) {
                    mismatches += "$case call $i: '$field' differs\n  desktop: ${w[field].toString().take(600)}\n  phone:   ${a[field].toString().take(600)}"
                }
            }
        }
        val wantResult = exp["result"]?.jsonPrimitive?.content
        val got = result ?: (out as? String)
        if (wantResult != null && wantResult != got) mismatches += "$case: result differs (desktop '$wantResult', phone '$got')"
    }

    @Test
    fun phonePromptsMatchDesktopGolden() {
        compareResult("language_prefix_de", langPrefix)
        compareResult("language_prefix_en", languages.systemPrefix(userData, "English"))
        compareResult("language_prefix_it", languages.systemPrefix(userData, "italiano"))
        compareResult("language_prefix_unknown", languages.systemPrefix(userData, ""))
        compareResult("translation_en_from_de", languages.translationSystemMessage(userData, "en", "de"))
        compareResult("translation_fr", languages.translationSystemMessage(userData, "fr"))

        compareCalls("extract_metadata", "{}") { extraction.metadata(job, it); null }
        compareCalls("extract_competences", "{}") { extraction.competences(job, it); null }
        val competences = inp["competences"]!!.jsonArray.map { it.jsonPrimitive.content }
        compareCalls("grade_competences", "{}") { extraction.grade(competences, cv, it); null }
        val rerankDocs = inp["rerank_docs"]!!.jsonObject.mapValues { it.value.jsonObject }
        val rerankReply = Json.pyDumps(buildJsonObject {
            put("scores", JsonArray(rerankDocs.keys.map { name ->
                buildJsonObject {
                    put("company_name", name)
                    put("comment", "")
                    put("score", 5)
                    put("similarities", JsonArray(emptyList()))
                    put("differences", JsonArray(emptyList()))
                }
            }))
        })
        compareCalls("rerank", rerankReply) { extraction.rerank(job, rerankDocs, it); null }

        compareCalls("research_flow", "report") { client ->
            val research = Research(
                prompts,
                CompaniesRepository({ error("no Firestore in unit tests") }, Embeddings { error("no embeddings in unit tests") }),
                { client },
                { emptyMap() },
                ModelOverrides(Catalogs(assets)),
            )
            research.companyReport(s("company_name"), job, client, s("research_combined_context"), ModelRole.COMPANY_RESEARCH.ref(), s("search_instructions"))
        }

        val structure = s("structure_instructions")
        val style = s("custom_style_instructions")
        val plan = s("letter_plan")
        compareCalls("plan", "plan") { generation.plan(inputs(structure = structure, languagePrefix = langPrefix), it) }
        compareCalls("plan_defaults", "plan") { generation.plan(inputs(topDocs = emptyList(), additional = "", hireProblem = ""), it) }
        val draftReply = """{"draft_letter": "x", "known_weaknesses": []}"""
        compareCalls("draft", draftReply) { generation.draft(inputs(style = style, languagePrefix = langPrefix), plan, it); null }
        compareCalls("draft_defaults", draftReply) { generation.draft(inputs(topDocs = emptyList(), companyReport = "", additional = "", hireProblem = ""), "", it); null }
        compareCalls("fancy", "fancy") { generation.fancy(letter, it) }

        val feedbackReply = """{"items": []}"""
        fun check(case: String, category: String, ins: LetterInputs, known: JsonArray) = compareCalls(case, feedbackReply) { client ->
            val checker = checks.checker(category, letter, ins)
            if (checker != null) checks.callItems(category, checker, ins.topDocs, known, client)
            null
        }
        for ((suffix, known) in listOf("" to kw, "_no_kw" to JsonArray(emptyList()))) {
            for (cat in FeedbackItems.CATEGORIES) check("feedback_$cat$suffix", cat, inputs(), known)
        }
        check("feedback_accuracy_plain", "accuracy", inputs(cvText = "", additional = ""), JsonArray(emptyList()))
        check("feedback_goal_fit_no_hire", "goal_fit", inputs(hireProblem = ""), JsonArray(emptyList()))
        check("feedback_user_fit_no_docs", "user_fit", inputs(topDocs = emptyList(), additional = ""), JsonArray(emptyList()))
        check("feedback_human_no_docs", "human", inputs(topDocs = emptyList()), JsonArray(emptyList()))

        // The phone deliberately sends the checker's context block with the follow-up (the desktop omits it,
        // so its model never sees the letter it is asked to quote). Everything else must match.
        val sc = inp["suggest_context"]!!.jsonObject
        val scCategory = sc["category"]!!.jsonPrimitive.content
        val scInputs = inputs(topDocs = emptyList())
        compareCalls("suggest_context", feedbackReply, ignoreFields = setOf("system_cache_prefix")) {
            checks.suggestContext(scCategory, sc["observation"]!!.jsonPrimitive.content, sc["existing"]!!.jsonArray, letter, scInputs, it)
            null
        }

        for (cat in FeedbackItems.CATEGORIES) compareResult("review_context_$cat", review.justificationContext(cat, letter, inputs(), kw))
        val reviewItems = inp["review_items"]!!.jsonArray.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content }
        val reviewReply = Json.pyDumps(buildJsonObject {
            put("results", JsonArray(reviewItems.map { (id, _) -> buildJsonObject { put("id", id); put("keep", true) } }))
        })
        val accuracyCtx = review.justificationContext("accuracy", letter, inputs(), kw)
        compareCalls("review_stage12", reviewReply) { review.stage12(it, "accuracy", reviewItems, accuracyCtx); null }
        val stage3 = objs(inp["stage3_items"]).map { Triple(it.str("id"), it.str("category"), it.str("observation")) }
        compareCalls("review_stage3", """{"groups": []}""") { review.stage3(it, stage3); null }
        val stage4 = objs(inp["stage4_rows"]).map { InputRow(it.str("id"), it.str("vendor"), it.str("category"), it.str("observation"), it.str("user_instructions")) }
        compareCalls("review_stage4", """{"clusters": []}""") { review.stage4(it, stage4); null }

        // Fixture items carry the desktop's stored `laya_*` names; the phone renames them when reading from Firestore.
        val fb = StoredFieldNames.fromStored(inp["rewrite_feedback"]!!).jsonObject.mapValues { it.value.jsonArray }
        compareCalls("rewrite", "revised") { generation.rewrite(letter, fb, it, plan, style, langPrefix) }

        val swissJob = inp["rerank_docs"]!!.jsonObject["Swiss Re"]!!.jsonObject.str("job_text")
        compareResult("decision_rag_state", DecisionJudge.ragState(job, "Swiss Re", swissJob))
        compareResult("decision_feedback_state", DecisionJudge.feedbackState(letter, inp["feedback_state_item"]!!.jsonObject, "accuracy"))
        checked += "decision_questions"
        val wantQuestions = Json.parse(expected["decision_questions"]!!.jsonObject["result"]!!.jsonPrimitive.content)
        if (wantQuestions != prompts.loadJson("decision_model/questions.json")) mismatches += "decision_questions: questions.json differs from the desktop questions"

        val unhandled = expected.keys - checked - notReplayed.keys
        assertTrue("Golden cases with no phone check (add one or list it in notReplayed): $unhandled", unhandled.isEmpty())
        val stale = notReplayed.keys - expected.keys
        assertTrue("notReplayed lists cases that no longer exist: $stale", stale.isEmpty())
        assertEquals("Phone prompts differ from desktop golden output:\n" + mismatches.joinToString("\n"), 0, mismatches.size)
    }

    private fun JsonObject.str(key: String) = this[key]?.jsonPrimitive?.content.orEmpty()
}
