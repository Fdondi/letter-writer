package io.github.fdondi.letterwriter.debug

import io.github.fdondi.letterwriter.BuildConfig
import io.github.fdondi.letterwriter.core.ApiKeys
import io.github.fdondi.letterwriter.core.FileSharedAssets
import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.llm.Catalogs
import io.github.fdondi.letterwriter.llm.ClientFactory
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.llm.RoleRef
import io.github.fdondi.letterwriter.llm.call
import io.github.fdondi.letterwriter.pipeline.Extraction
import io.github.fdondi.letterwriter.pipeline.FeedbackChecks
import io.github.fdondi.letterwriter.pipeline.FeedbackReview
import io.github.fdondi.letterwriter.pipeline.LetterGeneration
import io.github.fdondi.letterwriter.pipeline.LetterInputs
import io.github.fdondi.letterwriter.pipeline.ModelOutput
import io.github.fdondi.letterwriter.pipeline.QuoteSpans
import io.github.fdondi.letterwriter.pipeline.getStr
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/** The debug harness replies are the files in `app/debug/fixtures`, and they parse as the real pipeline expects. */
class FakePaidApisTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val assets = FileSharedAssets(repoRoot)
    private val prompts = Prompts(assets)
    private val fixtures = DebugFixtures.fromDirectory(repoRoot.resolve("app/debug/fixtures"))
    private val client = FakeLlmClient(ModelVendor.OPENAI, fixtures)
    private val generation = LetterGeneration(prompts)
    private val extraction = Extraction(prompts)
    private val checks = FeedbackChecks(prompts, generation::defaultStyle)

    private val inputs = LetterInputs(
        cvText = "FAKE CV used only to exercise the harness. Not a résumé.",
        jobText = "FAKE Fixture Works is hiring a FAKE Fixture Engineer. This posting is fixture data.",
        companyReport = "[FAKE FIXTURE] company report",
        topDocs = emptyList(),
        additionalUserInfo = "",
        hireProblem = "[FAKE FIXTURE] hire problem",
        languagePrefix = "",
        styleInstructions = "",
        structureInstructions = "",
    )

    @Test
    fun versionNameMatchesTheChangelogTheWebReads() {
        val line = repoRoot.resolve("letter_writer_web/public/app-version.txt").readLines().first { it.isNotBlank() }
        val version = line.substringBefore(" - ").trim()
        assertEquals(version, BuildConfig.VERSION_NAME)
    }

    @Test
    fun factoryReplacesTheVendorWithoutAnApiKey() = runBlocking {
        val factory = ClientFactory(
            Catalogs(assets),
            ApiKeys(emptyMap()),
            emptyMap(),
            debugClient = { vendor -> FakeLlmClient(vendor, fixtures) },
        )
        val plan = factory.create(ModelVendor.ANTHROPIC).call(
            ModelRole.LETTER_PLAN,
            "",
            listOf(prompts.load("generation/plan_user.txt")),
        )
        assertTrue(plan.contains("[FAKE FIXTURE]"))
    }

    @Test
    fun unrecognizedCallThrowsInsteadOfInventingAReply() {
        try {
            FakeLlmClient.fixtureName(RoleRef.ModelId("gpt-unknown"), "", listOf("hello"), search = false)
            fail("an unrecognized call must throw")
        } catch (e: IllegalStateException) {
            assertTrue(e.message.orEmpty().contains("Paid APIs were not called"))
        }
    }

    @Test
    fun extractionDraftFeedbackAndRewriteUseLabeledFixtures() = runBlocking {
        val (meta, metaWarning) = extraction.metadata(inputs.jobText, client)
        assertEquals(null, metaWarning)
        assertEquals("FAKE Fixture Works", meta.getStr("company_name"))
        assertEquals("FAKE Contact", (meta["point_of_contact"] as JsonObject).getStr("name"))

        val (competences, compWarning) = extraction.competences(inputs.jobText, client)
        assertEquals(null, compWarning)
        assertTrue(competences.hireProblem.contains("[FAKE FIXTURE]"))
        assertEquals(listOf("FixtureStack"), competences.byCategory["critical"])

        val (graded, gradeWarning) = extraction.grade(listOf("FixtureStack", "FixtureLang"), inputs.cvText, client)
        assertEquals(null, gradeWarning)
        assertEquals("Professional", graded["FixtureStack"])
        assertEquals("Brief experience", graded["FixtureLang"])

        val plan = generation.plan(inputs, client)
        assertTrue(plan.contains("[FAKE FIXTURE]"))

        val (letter, weaknesses) = generation.draft(inputs, plan, client)
        assertTrue(letter.contains("[FAKE FIXTURE]"))
        assertTrue(letter.contains("I led the FAKE fixture migration."))
        assertTrue(weaknesses.isNotEmpty())

        val spans = QuoteSpans { error("embeddings must not be called for an exact fixture quote") }
        val span = spans.resolve(letter, "I led the FAKE fixture migration.")
        assertEquals("exact", span?.method)
        assertTrue(spans.failures.isEmpty())

        val results = checks.runAll(letter, inputs, JsonArray(emptyList()), client)
        val instruction = results.getValue("instruction").items.single()
        assertEquals(null, results.getValue("instruction").error)
        assertTrue(instruction.getStr("observation").contains("[FAKE FIXTURE]"))
        assertEquals("PLEASE_FIX", instruction.getStr("type"))
        assertEquals("INPUT_NEEDED", results.getValue("accuracy").items.single().getStr("status"))
        assertEquals("ALREADY_GOOD", results.getValue("precision").items.single().getStr("type"))
        assertTrue(results.getValue("company_fit").items.isEmpty())
        assertEquals(null, results.getValue("human").error)
        assertTrue(results.getValue("human").items.isEmpty())

        val review = FeedbackReview(prompts, checks, generation::defaultStyle)
        val reviewed = review.reviewForVendor(
            client,
            letter,
            results.mapValues { it.value.items },
            inputs,
            "openai",
            JsonArray(emptyList()),
        )
        assertTrue(reviewed.getValue("instruction").single().getStr("observation").contains("[FAKE FIXTURE]"))
        assertTrue(review.warnings.none { "did not return JSON" in it })

        val rewritten = generation.rewrite(
            letter,
            mapOf(
                "instruction" to JsonArray(
                    listOf(
                        buildJsonObject {
                            put("type", "PLEASE_FIX")
                            put("observation", "[FAKE FIXTURE] change the close")
                            put("status", "NOT_NEEDED")
                        },
                    ),
                ),
            ),
            client,
            plan,
            "",
            "",
        )
        assertTrue(rewritten.contains("The rewrite fixture adds this sentence"))
        val fancy = generation.fancy(rewritten, client)
        assertTrue(fancy.contains("The fancy fixture adds this sentence"))
        assertTrue(fancy.contains("[FAKE FIXTURE]"))
    }
}
