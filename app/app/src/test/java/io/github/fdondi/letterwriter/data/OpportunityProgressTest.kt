package io.github.fdondi.letterwriter.data

import io.github.fdondi.letterwriter.core.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** The Running tab's line, from the `progress` the desktop batch writes while it drafts. */
class OpportunityProgressTest {
    private fun job(progress: String?) = Opportunity(
        "job",
        Json.parse("""{"status": "drafting", "updated_at": "2026-10-25T02:54:43Z"${progress?.let { ", \"progress\": $it" } ?: ""}}""").jsonObject,
    )

    @Test
    fun eachStepHasItsLine() {
        assertEquals("Reading the posting", job("""{"step": "reading", "vendors_done": [], "vendors_total": 8}""").progressLine)
        assertEquals("Researching the company", job("""{"step": "research", "vendors_done": [], "vendors_total": 8}""").progressLine)
        assertEquals(
            "Drafting · 2 of 8 vendors done",
            job("""{"step": "drafting", "vendors_done": ["claude_code", "openai"], "vendors_total": 8, "started_at": "2026-10-25T02:54:44Z"}""").progressLine,
        )
        assertEquals("2026-10-25T02:54:44Z", job("""{"step": "drafting", "vendors_done": [], "vendors_total": 2, "started_at": "2026-10-25T02:54:44Z"}""").runningSince)
    }

    @Test
    fun noReportYetOrAnUnknownStepShowsNothing() {
        assertEquals("", job(null).progressLine)
        assertEquals("", job("""{"step": "something new"}""").progressLine)
        assertEquals("", job(null).runningSince)
    }
}
