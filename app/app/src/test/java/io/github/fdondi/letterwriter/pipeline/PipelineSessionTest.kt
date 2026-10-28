package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.data.Opportunity
import io.github.fdondi.letterwriter.data.OpportunityStatus
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Opens what the desktop batch writes (`letter_writer/tests/fixtures/opportunity_session.json`,
 * kept in sync with `letter_writer.batch` by `test_session_fixture_matches_what_the_batch_writes`).
 */
class PipelineSessionTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val fixture = Json.parse(repoRoot.resolve("letter_writer/tests/fixtures/opportunity_session.json").readText()).jsonObject
    private val opportunity = Opportunity("fixture-opportunity", fixture.getValue("opportunity").jsonObject)
    private val state = fixture.getValue("state").jsonObject

    @Test
    fun theDesktopsDraftsOpenAsFinalLettersInVendorOrder() {
        assertEquals(OpportunityStatus.READY, opportunity.status)
        val session = PipelineSession.toWorkSession(opportunity, state)
        assertEquals(listOf("openai", "claude_code"), session.vendors)
        assertEquals("fixture-opportunity", session.opportunityId)
        for (vendor in session.vendors) {
            val work = session.vendorWork(vendor)
            assertEquals(vendor, VendorStage.FINAL, work.stage)
            assertTrue(vendor, work.draftLetter.startsWith("[$vendor]"))
            assertTrue(vendor, work.finalLetter.startsWith("[$vendor]"))
            assertTrue(vendor, work.letterPlan.isNotBlank())
        }
    }

    @Test
    fun intakeComesFromTheDesktopExtraction() {
        val intake = PipelineSession.toWorkSession(opportunity, state).intake
        assertEquals("FAKE Fixture Works", intake.companyName)
        assertEquals("FAKE Fixture Engineer", intake.jobTitle)
        assertTrue(intake.jobText.isNotBlank())
        assertTrue(intake.extracted)
        assertEquals(PipelineSession.DESKTOP_REPORT, intake.researchSource)
        assertTrue(intake.companyReport.isNotBlank())
        assertTrue(intake.warnings.toString(), intake.warnings.any { it.contains("gemini", ignoreCase = true) && "fake failure for the fixture" in it })
    }

    @Test
    fun openQuestionsMatchTheDesktopCount() {
        val session = PipelineSession.toWorkSession(opportunity, state)
        assertEquals(opportunity.inputNeededCount, PipelineSession.openQuestions(session))
        assertTrue(opportunity.inputNeededCount > 0)
    }

    @Test
    fun claudeCodeIsShownButRewrittenByAPhoneVendor() {
        assertFalse(PipelineSession.isPhoneVendor("claude_code"))
        assertTrue(PipelineSession.isPhoneVendor("openai"))
        assertEquals("Anthropic (Claude Code)", PipelineSession.label("claude_code"))
        assertTrue(PipelineSession.STAND_INS.getValue("claude_code").isNotEmpty())
    }

    @Test
    fun aSessionWithoutDraftsOpensEmptyInsteadOfCrashing() {
        val session = PipelineSession.toWorkSession(opportunity, JsonObject(emptyMap()))
        assertEquals(emptyList<String>(), session.vendors)
        assertEquals(opportunity.url, session.intake.sourceUrl)
    }
}
