package io.github.fdondi.letterwriter.data

import com.google.firebase.Timestamp
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class OpportunityRulesTest {
    private val sub = "100200300400500600700"
    private val now = Timestamp(1_790_000_000, 0)
    private val url = "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7/?utm_source=mail"

    private fun existing(status: String, user: String = sub, link: String = "https://www.jobs.ch/x") = Opportunity(
        OpportunityRules.idFor(sub, CaptureRequest(text = "", url = url, via = "share_url")),
        JsonObject(mapOf("user_id" to JsonPrimitive(user), "status" to JsonPrimitive(status), "url" to JsonPrimitive(link))),
    )

    @Test
    fun newJobWithTextIsCapturedUnderTheDesktopsId() {
        val plan = OpportunityRules.planCapture(sub, CaptureRequest("Senior engineer at V-ZUG", url, "share_text"), null, now)
        assertEquals(OpportunityStatus.CAPTURED, plan.outcome.status)
        assertEquals(OpportunityKeys.documentId(sub, "jobs.ch:6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7"), plan.id)
        val fields = plan.fields!!
        assertEquals("captured", fields["status"])
        assertEquals("jobs.ch", fields["source"])
        assertEquals("https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7", fields["url"])
        assertEquals("Senior engineer at V-ZUG", (fields["capture"] as Map<*, *>)["text"])
    }

    @Test
    fun desktopSettingsTravelWithTheJob() {
        val request = CaptureRequest("Senior engineer", url, "share_text", vendorsRequested = listOf("claude_code", "openai"), rewriteRounds = 5, finalFeedback = false)
        val fields = OpportunityRules.planCapture(sub, request, null, now).fields!!
        assertEquals(2L, fields["rewrite_rounds"])
        assertEquals(false, fields["final_feedback"])
        assertEquals(listOf("claude_code", "openai"), fields["vendors_requested"])
        // Sending the same posting again with other settings updates them.
        val again = OpportunityRules.planCapture(sub, request.copy(rewriteRounds = 0, finalFeedback = true), existing("captured"), now).fields!!
        assertEquals(0L, again["rewrite_rounds"])
        assertEquals(true, again["final_feedback"])
        // Not chosen: left to the batch's defaults.
        val plain = OpportunityRules.planCapture(sub, CaptureRequest("Senior engineer", url, "share_text"), null, now).fields!!
        assertNull(plain["rewrite_rounds"])
        assertNull(plain["final_feedback"])
    }

    @Test
    fun newJobWithOnlyALinkWaitsForItsText() {
        val plan = OpportunityRules.planCapture(sub, CaptureRequest("", url, "share_url"), null, now)
        assertEquals(OpportunityStatus.APPROVED, plan.outcome.status)
        assertNull(plan.fields!!["capture"])
    }

    @Test
    fun pastedTextWithoutLinkUsesTheTextKey() {
        val plan = OpportunityRules.planCapture(sub, CaptureRequest("  Job  text ", "", "share_text"), null, now)
        assertEquals(OpportunityKeys.textKey("Job text"), plan.fields!!["canonical_key"])
        assertEquals("manual", plan.fields!!["source"])
    }

    @Test
    fun textRequeuesOpenJobsButLeavesDesktopAndFinishedOnesAlone() {
        for (status in listOf("proposed", "approved", "skipped", "captured", "failed")) {
            val plan = OpportunityRules.planCapture(sub, CaptureRequest("text", url, "share_text"), existing(status), now)
            assertEquals(status, OpportunityStatus.CAPTURED, plan.outcome.status)
            assertEquals(status, "captured", plan.fields!!["status"])
        }
        for (status in listOf("drafting", "ready", "done", "applied")) {
            val plan = OpportunityRules.planCapture(sub, CaptureRequest("text", url, "share_text"), existing(status), now)
            assertNull(status, plan.fields)
            assertEquals(OpportunityStatus.fromKey(status), plan.outcome.status)
        }
    }

    @Test
    fun aBareLinkOnlyApprovesProposedOrSkippedJobs() {
        assertEquals(
            "approved",
            OpportunityRules.planCapture(sub, CaptureRequest("", url, "share_url"), existing("skipped"), now).fields!!["status"],
        )
        assertNull(OpportunityRules.planCapture(sub, CaptureRequest("", url, "share_url"), existing("captured"), now).fields)
    }

    @Test
    fun anotherUsersJobIsRejected() {
        assertThrows(SecurityException::class.java) {
            OpportunityRules.planCapture(sub, CaptureRequest("t", url, "share_text"), existing("proposed", user = "someone-else"), now)
        }
    }

    @Test
    fun thePhoneCannotSetDesktopStates() {
        for (to in listOf(OpportunityStatus.DRAFTING, OpportunityStatus.READY, OpportunityStatus.FAILED)) {
            assertThrows(IllegalArgumentException::class.java) {
                OpportunityRules.checkTransition(existing("captured"), "id", sub, setOf(OpportunityStatus.CAPTURED), to)
            }
        }
        assertThrows(IllegalStateException::class.java) {
            OpportunityRules.checkTransition(existing("drafting"), "id", sub, setOf(OpportunityStatus.PROPOSED), OpportunityStatus.APPROVED)
        }
        OpportunityRules.checkTransition(existing("proposed"), "id", sub, setOf(OpportunityStatus.PROPOSED), OpportunityStatus.APPROVED)
    }

    @Test
    fun emptyCaptureIsRefused() {
        assertThrows(IllegalArgumentException::class.java) {
            OpportunityRules.planCapture(sub, CaptureRequest(" ", " ", "share_text"), null, now)
        }
    }
}
