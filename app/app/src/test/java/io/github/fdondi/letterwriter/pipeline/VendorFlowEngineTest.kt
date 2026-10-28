package io.github.fdondi.letterwriter.pipeline

import android.app.Application
import android.content.Context
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.Backend
import io.github.fdondi.letterwriter.core.FileSharedAssets
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.data.DocumentStore
import io.github.fdondi.letterwriter.data.OpportunityStatus
import io.github.fdondi.letterwriter.data.SimilarDocument
import io.github.fdondi.letterwriter.debug.DebugFixtures
import io.github.fdondi.letterwriter.debug.FakeLlmClient
import io.github.fdondi.letterwriter.demo.DemoData
import io.github.fdondi.letterwriter.demo.DemoMode
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.llm.RoleRef
import io.github.fdondi.letterwriter.llm.UsageTotals
import io.github.fdondi.letterwriter.llm.currentUsageCollector
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.util.Collections
import java.util.concurrent.ConcurrentHashMap

/**
 * The phone's letter flow end to end on the JVM: extraction, research, plan, draft, the seven
 * checks and their review, answers, rewrite, assembly and save. Data is the demo account (in
 * memory); every model reply is a fixture from `app/debug/fixtures`, so nothing leaves the machine.
 * Faults are injected per vendor and role to show a failing call ends that step, not the app.
 */
class VendorFlowEngineTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val fixtures = DebugFixtures { name ->
        if (name == DemoData.JOBS_FIXTURE) {
            repoRoot.resolve("ui-harness/fixtures/opportunities/opportunities.json").readText()
        } else {
            repoRoot.resolve("app/debug/fixtures/$name").readText()
        }
    }
    private val sub = DemoMode.USER.sub
    private lateinit var dir: File
    private val uncaught: MutableList<Throwable> = Collections.synchronizedList(ArrayList())
    private var previousHandler: Thread.UncaughtExceptionHandler? = null

    private val jobText = """
        FAKE Fixture Works is hiring a FAKE Fixture Engineer in Zug.
        You build C++ and CUDA software for embedded GPU systems. This posting is fixture data.
    """.trimIndent()

    @Before
    fun setUp() {
        dir = Files.createTempDirectory("lw-engine").toFile()
        previousHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { _, e -> uncaught += e }
    }

    @After
    fun tearDown() {
        Thread.setDefaultUncaughtExceptionHandler(previousHandler)
        dir.deleteRecursively()
        assertEquals("exceptions escaped to a thread's uncaught handler", emptyList<Throwable>(), uncaught.toList())
    }

    /** Context methods the graph touches on the JVM (the android.jar stubs return null otherwise). */
    private class TestApp(private val dir: File) : Application() {
        override fun getApplicationContext(): Context = this
        override fun getFilesDir(): File = dir
        override fun getPackageName(): String = "io.github.fdondi.letterwriter.test"
    }

    /**
     * Fixture replies ([FakeLlmClient]) plus a similar-letter ranking, which the debug harness
     * never answers, and per-call faults keyed by vendor and role.
     */
    private inner class ScriptedLlm {
        val calls: MutableList<Pair<String, String>> = Collections.synchronizedList(ArrayList())
        /** Role to the user message of each call. */
        val prompts: MutableList<Pair<String, String>> = Collections.synchronizedList(ArrayList())
        val faults = ConcurrentHashMap<Pair<String, String>, () -> String>()

        fun client(vendor: ModelVendor): LlmClient = object : LlmClient {
            override val vendor = vendor

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
                // Like the real clients: a call outside a cost phase is an error, and usage is recorded.
                currentUsageCollector().add(vendor.key, UsageTotals(cost = 0.001, inputTokens = 100, outputTokens = 50, requests = 1))
                calls += vendor.key to role.recorded
                prompts += role.recorded to userMessages.joinToString("\n")
                faults[vendor.key to role.recorded]?.let { return it() }
                if (role == RoleRef.Role(ModelRole.RAG_RANKER)) return ranking(userMessages.joinToString("\n"))
                return FakeLlmClient(vendor, fixtures).call(role, system, userMessages, search, responseFormat, cachePrefix, systemCachePrefix, promptCacheKey)
            }
        }

        /** `{"scores": [...]}` for every company in the rerank prompt's JSON block. */
        private fun ranking(prompt: String): String {
            val mapping = Json.parse(prompt.substringAfter("Other Descriptions (JSON):\n")).jsonObject
            return buildJsonObject {
                put("scores", buildJsonArray {
                    mapping.values.forEachIndexed { i, v ->
                        add(buildJsonObject {
                            put("company_name", v.asObjectOrNull()?.get("company_name").pyStr())
                            put("score", 8 - i)
                            put("comment", "[FAKE FIXTURE] ranking")
                            put("similarities", buildJsonArray { add(JsonPrimitive("C++")) })
                            put("differences", buildJsonArray { })
                        })
                    }
                })
            }.toString()
        }
    }

    /** The demo account's documents, but similar-letter search returns them all (the demo returns none). */
    private class SearchableDocuments(private val inner: DocumentStore) : DocumentStore by inner {
        override suspend fun similar(sub: String, jobText: String, limit: Int): List<SimilarDocument> =
            inner.list(sub, 50).mapIndexed { i, d -> SimilarDocument(d, 0.9 - i * 0.1) }
    }

    private fun graph(llm: ScriptedLlm): AppGraph = AppGraph(
        TestApp(dir),
        { g ->
            val b = DemoData.backend(g) { }
            Backend(b.auth, b.profiles, SearchableDocuments(b.documents), b.companies, b.opportunities, b.embeddings, b.bigQuery)
        },
        llmOverride = llm::client,
        dataDir = dir,
        assets = FileSharedAssets(repoRoot),
        debugFixtures = fixtures,
    )

    private suspend fun AppGraph.signIn(): AppGraph = apply { profiles.load(sub) }

    private suspend fun AppGraph.until(what: String, timeoutMs: Long = 30_000, ok: (WorkSession) -> Boolean): WorkSession =
        try {
            withTimeout(timeoutMs) {
                while (true) {
                    val s = workSessions.current()
                    if (s != null && ok(s)) return@withTimeout s
                    delay(20)
                }
                @Suppress("UNREACHABLE_CODE")
                error("unreachable")
            }
        } catch (e: Exception) {
            throw AssertionError("Timed out waiting for $what. Session: ${workSessions.current()}\nMessage: ${flow.message.value}", e)
        }

    private suspend fun AppGraph.idle() = withTimeout(60_000) { flow.running.first { it.isEmpty() } }

    private fun VendorWork.pleaseFix(): List<Pair<String, JsonObject>> = FeedbackItems.CATEGORIES.flatMap { cat ->
        items(cat).filter { it["type"].pyStr() == FeedbackUi.PLEASE_FIX && !FeedbackUi.isHidden(it) }.map { cat to it }
    }

    @Test
    fun aLetterFromScratchReachesTheSavedExample() = runBlocking<Unit> {
        val llm = ScriptedLlm()
        val g = graph(llm).signIn()
        val vendors = listOf("openai", "anthropic")

        g.flow.startLetter(jobText, "", vendors, includePlanStep = true)
        val read = g.until("extraction") { it.intake.extracted }
        g.idle()
        assertEquals("FAKE Fixture Works", read.intake.companyName)
        assertTrue("competences: ${read.intake.competences}", read.intake.competences.isNotEmpty())
        assertEquals("the ranked similar letters are pre-selected", 2, read.intake.selectedDocIds.size)

        assertTrue(g.flow.research())
        g.idle()
        val researched = g.workSessions.current()!!
        assertTrue("report: ${researched.intake.warnings}", researched.intake.companyReport.isNotBlank())

        for (v in vendors) assertTrue(g.flow.startVendor(v))
        g.idle()
        for (v in vendors) {
            val w = g.workSessions.current()!!.vendorWork(v)
            assertNull("$v: ${w.error}", w.error)
            assertEquals(VendorStage.PLAN, w.stage)
        }

        for (v in vendors) assertTrue(g.flow.approvePlan(v, g.workSessions.current()!!.vendorWork(v).letterPlan))
        g.idle()
        val drafted = g.workSessions.current()!!
        for (v in vendors) {
            val w = drafted.vendorWork(v)
            assertNull("$v: ${w.error}", w.error)
            assertNull("$v is still marked busy", w.busy)
            assertEquals(VendorStage.DRAFT, w.stage)
            assertTrue(w.draftLetter.contains("[FAKE FIXTURE]"))
            assertTrue("$v has feedback", w.feedback.isNotEmpty())
            assertEquals("$v check errors", emptyMap<String, String>(), w.checkErrors)
        }

        // Answer the question, approve every comment, then approve the draft (rewrite).
        for (v in vendors) {
            for ((cat, item) in drafted.vendorWork(v).pleaseFix()) {
                val id = item["id"].pyStr()
                if (item["status"].pyStr() == "INPUT_NEEDED") {
                    g.flow.answerInput(v, cat, id, "[FAKE] The migration moved billing to Kotlin.", toCv = true, toAgents = true)
                } else {
                    g.flow.approveItem(v, cat, id)
                }
            }
        }
        g.until("every comment approved") { s -> vendors.all { s.vendorWork(it).allApproved() } }
        for (v in vendors) assertTrue(g.flow.approveDraft(v, fancy = v == "anthropic"))
        g.idle()
        val finished = g.workSessions.current()!!
        for (v in vendors) {
            val w = finished.vendorWork(v)
            assertNull("$v: ${w.error}", w.error)
            assertEquals(VendorStage.FINAL, w.stage)
        }
        assertTrue(finished.vendorWork("openai").finalLetter.contains("The rewrite fixture adds this sentence"))
        // The polish pass runs on the rewrite and replaces its text.
        assertTrue(finished.vendorWork("anthropic").finalLetter.contains("The fancy fixture adds this sentence"))

        g.flow.useWholeLetter("openai")
        val assembled = g.until("assembly") { it.paragraphs.isNotEmpty() }
        val id = g.flow.saveLetter()
        assertEquals(assembled.finalText, g.documents.get(sub, id)?.text("letter_text"))
        val notes = g.profiles.current().extraInfo
        assertTrue("the answer is kept as a CV note: $notes", notes.any { it["user_context"].pyStr().contains("migration moved billing") })
        assertTrue("every call ran inside a cost phase", llm.calls.isNotEmpty())
    }

    @Test
    fun aFailingCallEndsOnlyItsStep() = runBlocking<Unit> {
        val llm = ScriptedLlm()
        val g = graph(llm).signIn()
        val vendors = listOf("openai", "anthropic", "gemini")
        // anthropic: an Error, which used to escape `catch (e: Exception)` and end the process.
        llm.faults["anthropic" to "letter_draft"] = { throw StackOverflowError("deep model reply") }
        // gemini: a reply that is never the JSON the draft step needs (it retries, then gives up).
        llm.faults["gemini" to "letter_draft"] = { "Sorry, I can't help with that. {not json" }
        // openai: the network drops during every feedback check.
        llm.faults["openai" to "feedback"] = { throw IOException("OpenAI response could not be read: unexpected end of stream") }

        g.flow.startLetter(jobText, "", vendors, includePlanStep = false)
        g.until("extraction") { it.intake.extracted }
        g.idle()
        for (v in vendors) g.flow.startVendor(v)
        g.idle()

        val s = g.workSessions.current()!!
        val anthropic = s.vendorWork("anthropic")
        assertTrue("anthropic error: ${anthropic.error}", anthropic.error.orEmpty().contains("StackOverflowError"))
        assertNull(anthropic.busy)
        val gemini = s.vendorWork("gemini")
        assertTrue("gemini error: ${gemini.error}", gemini.error.orEmpty().contains("Draft letter generation failed"))
        val openai = s.vendorWork("openai")
        assertNull("openai error: ${openai.error}", openai.error)
        assertEquals(VendorStage.DRAFT, openai.stage)
        assertTrue("every check failed and says so: ${openai.checkErrors}", openai.checkErrors.isNotEmpty())

        // Try again after the fault is gone.
        llm.faults.remove("anthropic" to "letter_draft")
        assertTrue(g.flow.startVendor("anthropic"))
        g.idle()
        val retried = g.workSessions.current()!!.vendorWork("anthropic")
        assertNull(retried.error)
        assertEquals(VendorStage.DRAFT, retried.stage)
    }

    @Test
    fun anUncaughtErrorInAQuickActionBecomesAMessage() = runBlocking<Unit> {
        val g = graph(ScriptedLlm()).signIn()
        g.flow.startLetter(jobText, "", listOf("openai"), includePlanStep = false)
        g.until("session") { true }
        // A transform that throws an Error, run through the same fire() path as every button.
        g.flow.updateIntake { throw NoSuchMethodError("java.util.List.removeFirst") }
        withTimeout(10_000) { g.flow.message.first { it != null } }
        assertTrue(g.flow.message.value.orEmpty().contains("NoSuchMethodError"))
        g.idle()
    }

    @Test
    fun desktopDraftsOpenAndARewriteOfClaudeCodeUsesAStandIn() = runBlocking<Unit> {
        val llm = ScriptedLlm()
        val g = graph(llm).signIn()
        val ready = g.opportunities.observe(sub).first().single { it.status == OpportunityStatus.READY }

        val opened = g.flow.openOpportunity(ready)
        assertEquals(ready.id, opened.opportunityId)
        assertEquals(listOf("openai", "claude_code"), opened.vendors)

        val (cat, question) = opened.vendorWork("claude_code").pleaseFix().first { it.second["status"].pyStr() == "INPUT_NEEDED" }
        g.flow.answerInput("claude_code", cat, question["id"].pyStr(), "[FAKE] Yes, three years of CUDA.", toCv = false, toAgents = false)
        g.until("answer saved") { s -> s.vendorWork("claude_code").items(cat).any { it["user_context"].pyStr().contains("three years") } }

        assertTrue(g.flow.refine("claude_code", fancy = false))
        g.idle()
        val w = g.workSessions.current()!!.vendorWork("claude_code")
        assertNull(w.error)
        assertTrue(w.finalLetter.contains("The rewrite fixture adds this sentence"))
        assertTrue("the rewrite ran on Anthropic: ${llm.calls}", ("anthropic" to "letter_refine") in llm.calls)

        g.flow.useWholeLetter("claude_code")
        g.until("assembly") { it.paragraphs.isNotEmpty() }
        val docId = g.flow.saveLetter()
        val done = g.opportunities.get(sub, ready.id)!!
        assertEquals(OpportunityStatus.DONE, done.status)
        assertEquals(docId, done.documentId)
    }

    @Test
    fun aDesktopParagraphIsRedraftedNowThroughTheApi() = runBlocking<Unit> {
        val llm = ScriptedLlm()
        val g = graph(llm).signIn()
        val ready = g.opportunities.observe(sub).first().single { it.status == OpportunityStatus.READY }
        g.flow.openOpportunity(ready)
        val w = g.workSessions.current()!!.vendorWork("claude_code")
        val view = ParagraphReview.of(w)
        val target = view.paragraphs.firstOrNull { it.comments.isNotEmpty() } ?: view.paragraphs[1]
        val picked = target.comments.ifEmpty { view.wholeLetter.take(1) }

        assertTrue(g.flow.redraftParagraph("claude_code", target.index, "Name the team.", picked))
        g.idle()
        val after = g.workSessions.current()!!.vendorWork("claude_code")
        assertTrue(after.paragraphEdits.getValue(target.index).contains("[FAKE FIXTURE] This paragraph was rewritten"))
        assertEquals(1, after.paragraphEdits.size)
        assertTrue("claude_code runs only on the desktop; Anthropic redrafts it: ${llm.calls}", ("anthropic" to "paragraph") in llm.calls)
        val prompt = llm.prompts.single { it.first == "paragraph" }.second
        assertTrue(prompt.contains(">>>\n${target.text}\n<<<"))
        assertTrue(prompt.contains("Name the team."))
        picked.forEach { assertTrue(prompt.contains(it.item["observation"].pyStr())) }
        assertTrue("the redraft is paid as an API call", after.totalCost > w.totalCost)

        g.flow.useWholeLetter("claude_code")
        val assembled = g.until("assembly") { it.paragraphs.isNotEmpty() }
        assertEquals(after.paragraphEdits.getValue(target.index), assembled.paragraphs[target.index].text)

        g.flow.restoreParagraph("claude_code", target.index)
        g.until("restored") { it.vendorWork("claude_code").paragraphEdits.isEmpty() }
    }

    @Test
    fun aStepCutShortByTheProcessDyingIsShownAsInterrupted() = runBlocking<Unit> {
        val first = graph(ScriptedLlm()).signIn()
        first.workSessions.update {
            WorkSession(
                intake = JobIntake(jobText = jobText, extracted = true),
                vendors = listOf("openai"),
                work = mapOf("openai" to VendorWork("openai", stage = VendorStage.PLAN, letterPlan = "plan", busy = "Writing the draft")),
            )
        }
        // A new engine on the same files is what the next app start sees.
        val restarted = graph(ScriptedLlm()).signIn()
        restarted.flow.running.value
        val s = restarted.until("interrupted step") { it.vendorWork("openai").busy == null }
        val error = s.vendorWork("openai").error
        assertNotNull(error)
        assertTrue(error!!, error.startsWith("Interrupted while “Writing the draft”"))
    }
}
