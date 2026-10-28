package io.github.fdondi.letterwriter.demo

import com.google.firebase.Timestamp
import io.github.fdondi.letterwriter.core.FileSharedAssets
import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.data.CaptureRequest
import io.github.fdondi.letterwriter.data.InMemoryOpportunityStore
import io.github.fdondi.letterwriter.data.InstructionDefaults
import io.github.fdondi.letterwriter.data.InstructionKind
import io.github.fdondi.letterwriter.data.OpportunityStatus
import io.github.fdondi.letterwriter.llm.Catalogs
import io.github.fdondi.letterwriter.llm.ModelOverrides
import io.github.fdondi.letterwriter.pipeline.PipelineSession
import io.github.fdondi.letterwriter.pipeline.VendorStage
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Demo mode's data, as the app seeds it from assets/fixtures (here read from the repository). */
class DemoDataTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val read: (String) -> String = { name ->
        if (name == DemoData.JOBS_FIXTURE) {
            repoRoot.resolve("ui-harness/fixtures/opportunities/opportunities.json").readText()
        } else {
            repoRoot.resolve("app/debug/fixtures/$name").readText()
        }
    }
    private val sub = DemoMode.USER.sub

    @Test
    fun demoJobsCoverEveryTabAndTheReadyOneOpensAsDrafts() = runTest {
        val (jobs, sessions) = DemoData.jobs(read)
        val store = InMemoryOpportunityStore(jobs, sessions)
        val listed = store.observe(sub).first()
        assertEquals(
            setOf("proposed", "approved", "captured", "failed", "ready", "skipped", "done", "applied"),
            listed.map { it.status.key }.toSet(),
        )
        val ready = listed.single { it.status == OpportunityStatus.READY }
        val state = store.loadSession(sub, ready.id) ?: error("the ready demo job has no drafts")
        val session = PipelineSession.toWorkSession(ready, state)
        assertEquals(listOf("openai", "claude_code"), session.vendors)
        assertTrue(session.vendors.all { session.vendorWork(it).stage == VendorStage.FINAL })
        assertTrue(PipelineSession.openQuestions(session) > 0)
        val applied = listed.single { it.status == OpportunityStatus.APPLIED }
        assertEquals("interview ×2 · rejected · praised", applied.outcomeLine)
        assertEquals(listOf("[FAKE] Your letter stood out to the team."), applied.feedbackQuotes)
        assertEquals("received", listed.single { it.status == OpportunityStatus.DONE }.outcomeLine)
        assertTrue(listed.single { it.status == OpportunityStatus.PROPOSED }.historyNote.startsWith("[FAKE] You applied"))
        // Nobody else sees the demo account's jobs.
        assertEquals(emptyList<Any>(), store.observe("someone-else").first())
    }

    @Test
    fun inMemoryStoreFollowsTheSameRulesAsFirestore() = runTest {
        val store = InMemoryOpportunityStore(now = { Timestamp(1_790_000_000, 0) })
        val url = "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7/"
        val link = store.capture(sub, CaptureRequest("", url, "share_url"))
        assertEquals(OpportunityStatus.APPROVED, link.status)
        val text = store.capture(sub, CaptureRequest("Posting text", url, "share_text"))
        assertEquals(link.id, text.id)
        assertEquals(OpportunityStatus.CAPTURED, text.status)
        assertEquals("Posting text", store.get(sub, link.id)!!.captureText)

        store.transition(sub, link.id, setOf(OpportunityStatus.CAPTURED), OpportunityStatus.SKIPPED, mapOf("skip_reason" to "Location"))
        assertEquals("Location", store.get(sub, link.id)!!.skipReason)
        assertThrows(IllegalStateException::class.java) {
            kotlinx.coroutines.runBlocking { store.transition(sub, link.id, setOf(OpportunityStatus.PROPOSED), OpportunityStatus.APPROVED) }
        }
        assertThrows(SecurityException::class.java) { kotlinx.coroutines.runBlocking { store.get("intruder", link.id) } }
        assertNull(store.loadSession(sub, link.id))
    }

    @Test
    fun demoProfileHasACvVendorsAndSavesInMemory() = runTest {
        val assets = FileSharedAssets(repoRoot)
        val profiles = DemoProfiles(InstructionDefaults(Prompts(assets)), ModelOverrides(Catalogs(assets)))
        val profile = profiles.load(sub)
        assertTrue(profile.cvRevisions.single()["content"].toString().contains("[DEMO]"))
        assertEquals(listOf("openai", "anthropic"), profile.defaultVendors)

        profiles.saveInstruction(sub, InstructionKind.STYLE, "Short sentences.")
        assertEquals("Short sentences.", profiles.current().styleInstructions())
        profiles.clearInstruction(sub, InstructionKind.STYLE)
        assertEquals("", profiles.current().customInstruction(InstructionKind.STYLE))
        profiles.appendCvRevision(sub, "New CV")
        assertEquals(2, profiles.current().cvRevisions.size)
        assertEquals(DemoProfiles.DEMO_KEY, profiles.loadApiKeys(sub).get("openai"))
    }

    @Test
    fun demoDocumentsListUpsertAndDelete() = runTest {
        val docs = DemoDocuments(DemoData.seedDocuments())
        assertEquals(listOf("demo-doc-2", "demo-doc-1"), docs.list(sub).map { it.id })
        val saved = docs.upsert(sub, buildJsonObject { put("company_name", "New AG"); put("letter_text", "Dear New AG") })
        assertEquals(saved.id, docs.list(sub).first().id)
        assertEquals(2, docs.saveFeedback(sub, saved.id, "Dear", JsonArray(listOf(buildJsonObject { }, buildJsonObject { }))))
        docs.delete(sub, saved.id)
        assertNull(docs.get(sub, saved.id))
        assertEquals(emptyList<Any>(), docs.similar(sub, "anything"))
    }

    @Test
    fun hashEmbeddingsAreDeterministicUnitVectors() = runTest {
        val (a, b, c) = HashEmbeddings().embedBatch(listOf("C++ CUDA engineer", "C++ CUDA engineer", "pastry chef"))
        assertTrue(a.contentEquals(b))
        assertEquals(1.0, a.sumOf { it * it }, 1e-9)
        assertTrue(a.zip(c.toList()).sumOf { (x, y) -> x * y } < 0.5)
    }
}
