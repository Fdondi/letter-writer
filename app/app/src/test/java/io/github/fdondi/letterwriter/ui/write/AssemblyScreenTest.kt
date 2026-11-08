package io.github.fdondi.letterwriter.ui.write

import android.app.Application
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.test.swipeRight
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.FileSharedAssets
import io.github.fdondi.letterwriter.debug.DebugFixtures
import io.github.fdondi.letterwriter.demo.DemoData
import io.github.fdondi.letterwriter.pipeline.FinalParagraph
import io.github.fdondi.letterwriter.pipeline.JobIntake
import io.github.fdondi.letterwriter.pipeline.VendorStage
import io.github.fdondi.letterwriter.pipeline.VendorWork
import io.github.fdondi.letterwriter.pipeline.WorkSession
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.coroutines.EmptyCoroutineContext
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * The Final tab on the JVM (Robolectric): the vendor letters sit side by side as swipeable tabs
 * under a higher level of swipeable tabs (Letters / Your letter / Info), and the Info page has
 * sub-tabs for every part of the job. Data is the demo account (in memory); nothing leaves the machine.
 */
@RunWith(RobolectricTestRunner::class)
@Config(application = AssemblyScreenTest.TestApp::class, sdk = [35])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class AssemblyScreenTest {
    @get:Rule
    val compose = createComposeRule(EmptyCoroutineContext)

    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val fixtures = DebugFixtures { name ->
        if (name == DemoData.JOBS_FIXTURE) {
            repoRoot.resolve("ui-harness/fixtures/opportunities/opportunities.json").readText()
        } else {
            repoRoot.resolve("app/debug/fixtures/$name").readText()
        }
    }

    /** Robolectric's application: an empty Application provides filesDir and the package name. */
    class TestApp : Application()

    private lateinit var graph: AppGraph

    @Before
    fun setUp() {
        val app = RuntimeEnvironment.getApplication()
        graph = AppGraph(
            app,
            { g -> DemoData.backend(g) { } },
            dataDir = app.filesDir,
            assets = FileSharedAssets(repoRoot),
            debugFixtures = fixtures,
        )
    }

    /** A session whose two vendors both have a finished letter, and one paragraph picked. */
    private fun twoVendorSession(): WorkSession {
        // Three and four paragraphs, so each letter's review card has its own paragraph count.
        val openaiLetter = "Dear Fixture Works team,\n\nthe OpenAI letter body.\n\nKind regards,\nDemo"
        val claudeLetter = "Dear Fixture Works team,\n\nthe Claude Code letter body, first paragraph.\n\nSecond paragraph of the Claude Code letter.\n\nKind regards,\nDemo"
        return WorkSession(
            intake = JobIntake(
                jobText = "FAKE Fixture Works is hiring a FAKE Fixture Engineer in Zug. C++ and CUDA.",
                companyName = "FAKE Fixture Works",
                jobTitle = "FAKE Fixture Engineer",
                location = "Zug",
                language = "English",
                salary = "CHF 120k",
                sourceUrl = "https://example.invalid/job",
                hireProblem = "They need a C++ engineer for the GPU team.",
                requirements = listOf("C++", "CUDA"),
                competences = JsonObject(
                    mapOf(
                        "C++" to buildJsonObject {
                            put("need", JsonPrimitive("high"))
                            put("level", JsonPrimitive("expert"))
                        },
                    ),
                ),
                additionalUserInfo = "FAKE about you",
                extracted = true,
                similarDocuments = listOf(
                    JsonObject(
                        mapOf(
                            "id" to JsonPrimitive("demo-doc-1"),
                            "company_name" to JsonPrimitive("Example Robotics AG"),
                            "role" to JsonPrimitive("Senior C++ Engineer"),
                            "score" to JsonPrimitive(9),
                        ),
                    ),
                ),
                selectedDocIds = listOf("demo-doc-1"),
                decisionDetail = "FAKE decision detail",
                companyReports = JsonObject(
                    mapOf("openai" to buildJsonObject { put("report", JsonPrimitive("FAKE company report")) }),
                ),
                researchSource = "fixture",
                selectedReportModel = "openai",
                companyReport = "FAKE company report",
                pointOfContact = JsonObject(mapOf("name" to JsonPrimitive("FAKE Jane Recruiter"))),
            ),
            vendors = listOf("openai", "claude_code"),
            work = mapOf(
                "openai" to VendorWork(vendor = "openai", stage = VendorStage.FINAL, finalLetter = openaiLetter),
                "claude_code" to VendorWork(vendor = "claude_code", stage = VendorStage.FINAL, finalLetter = claudeLetter),
            ),
            paragraphs = listOf(FinalParagraph(vendor = "openai", originalText = "Dear Fixture Works team,", text = "Dear Fixture Works team,")),
        )
    }

    /** The session loads from the store on a background thread; wait until a node shows up. */
    private fun waitForText(text: String, substring: Boolean = false) {
        val deadline = System.currentTimeMillis() + 20_000
        while (System.currentTimeMillis() < deadline) {
            compose.waitForIdle()
            val found = if (substring) {
                compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes()
            } else {
                compose.onAllNodesWithText(text).fetchSemanticsNodes()
            }
            if (found.isNotEmpty()) return
            Thread.sleep(50)
        }
        compose.onNodeWithText(text, substring = substring).assertExists()
    }

    private fun assertTabSelected(label: String) {
        compose.waitForIdle()
        val selected = compose.onAllNodesWithText(label).fetchSemanticsNodes()
            .any { it.config.getOrNull(SemanticsProperties.Selected) == true }
        assertTrue("tab '$label' should be selected", selected)
    }

    /**
     * A tab exists. Matched by role, not by text alone: "Your letter" is also the title of the
     * letter card on the neighbouring page, so the text matches two nodes.
     */
    private fun assertTabExists(label: String) {
        compose.waitForIdle()
        val isTab = compose.onAllNodesWithText(label).fetchSemanticsNodes()
            .any { it.config.getOrNull(SemanticsProperties.Role) == Role.Tab }
        assertTrue("tab '$label' should exist", isTab)
    }

    @Test
    fun lettersAreSwipeableTabsUnderAHigherLevelOfSwipeableTabs() {
        runBlocking {
            graph.workSessions.update { twoVendorSession() }
            compose.setContent { MaterialTheme { AssemblyScreen(graph) } }
            waitForText("Letters")

            // The higher level of tabs: the letters, the letter being built, and the info.
            assertTabSelected("Letters")
            assertTabExists("Your letter")
            assertTabExists("Info")

            // The letters sit side by side as tabs, one per vendor, instead of a vertical list.
            compose.onNodeWithText("3 paragraph(s) · no comments").assertIsDisplayed()
            compose.onNodeWithText("4 paragraph(s) · no comments").assertIsNotDisplayed()
            assertTabSelected("OpenAI")

            // The paragraphs are shown straight away: no "Review paragraphs" toggle, no "Use whole letter" button.
            assertTrue(compose.onAllNodesWithText("Add to your letter").fetchSemanticsNodes().isNotEmpty())
            compose.onNodeWithText("Use whole letter").assertDoesNotExist()
            compose.onNodeWithText("Review paragraphs").assertDoesNotExist()
            // No how-to banner above the letter tabs: the vendor tab row sits directly under the main one.
            compose.onNodeWithText("Each paragraph shows its comments", substring = true).assertDoesNotExist()

            // Swiping laterally goes from one letter to the other.
            compose.onNodeWithText("3 paragraph(s) · no comments").performTouchInput { swipeLeft(durationMillis = 100) }
            compose.waitForIdle()
            compose.onNodeWithText("4 paragraph(s) · no comments").assertIsDisplayed()
            compose.onNodeWithText("3 paragraph(s) · no comments").assertIsNotDisplayed()
            assertTabSelected("Anthropic (Claude Code)")

            // The info tab has sub-tabs for the parts of the job.
            compose.onNodeWithText("Info").performClick()
            compose.waitForIdle()
            for (tab in listOf("Job offer", "Company", "Goal", "Competences", "Notes")) {
                compose.onNodeWithText(tab).assertExists()
            }
            compose.onNodeWithText("Examples").assertDoesNotExist()
            assertTabSelected("Info")
            compose.onNodeWithText("FAKE Fixture Works is hiring a FAKE Fixture Engineer in Zug. C++ and CUDA.").assertIsDisplayed()

            // A sub-tab shows its part: the company search.
            compose.onNodeWithText("Company").performClick()
            compose.waitForIdle()
            compose.onNodeWithText("Company report used by every vendor").assertIsDisplayed()
            compose.onNodeWithText("FAKE company report").assertIsDisplayed()

            // A sub-tab shows its part: the deduced goal.
            compose.onNodeWithText("Goal").performClick()
            compose.waitForIdle()
            compose.onNodeWithText("They need a C++ engineer for the GPU team.").assertIsDisplayed()
            // The requirements list is gone: it duplicated the competences (same skills, no ratings).
            compose.onNodeWithText("Requirements").assertDoesNotExist()

            // The competences tab keeps the skills with their need and level.
            compose.onNodeWithText("Competences").performClick()
            compose.waitForIdle()
            compose.onNodeWithText("Key competences").assertIsDisplayed()

            // Swiping right brings up the final letter that is being built.
            compose.onNodeWithText("Info").performClick()
            compose.onNodeWithText("Company").performClick()
            compose.waitForIdle()
            compose.onNodeWithText("FAKE company report").performTouchInput { swipeRight(durationMillis = 100) }
            compose.waitForIdle()
            compose.onNodeWithText("Copy").assertIsDisplayed()
            assertTabSelected("Your letter")

            // Swiping left brings up the info.
            compose.onNodeWithText("Copy").performTouchInput { swipeLeft(durationMillis = 100) }
            compose.waitForIdle()
            compose.onNodeWithText("Job offer").assertIsDisplayed()
            assertTabSelected("Info")
        }
    }

    @Test
    fun noFinishedLetterYetShowsAMessageOnTheLettersPage() {
        runBlocking {
            graph.workSessions.update {
                WorkSession(vendors = listOf("openai"), work = mapOf("openai" to VendorWork(vendor = "openai")))
            }
            compose.setContent { MaterialTheme { AssemblyScreen(graph) } }
            waitForText("No vendor has a finished letter yet. Approve a draft on the Letters tab first.")

            compose.onNodeWithText("No vendor has a finished letter yet. Approve a draft on the Letters tab first.").assertIsDisplayed()
            // The higher level of tabs is still there, and the letter being built is empty.
            assertTabExists("Your letter")
            assertTabExists("Info")
            compose.onNodeWithText("Add paragraphs from the letters on the Letters page.").assertExists()
        }
    }
}
