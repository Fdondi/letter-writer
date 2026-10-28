package io.github.fdondi.letterwriter.pipeline

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Which comments the paragraph review shows, and on which paragraph. */
class ParagraphReviewTest {
    private val letter = "Dear team,\n\nI led the billing migration to Kotlin.\n\nI enjoy  mentoring juniors.\n\nKind regards"

    private fun item(id: String, quote: String, type: String = "PLEASE_FIX", status: String = "NOT_NEEDED", answer: String = "") = buildJsonObject {
        put("id", id)
        put("observation", "observation $id")
        put("type", type)
        put("status", status)
        put("quote", quote)
        put("user_context", answer)
        put("user_instructions", if (status == "INPUT_NEEDED") "question $id" else "")
    }

    private fun work(vararg items: JsonObject, final: String = "", commentsOn: String? = null, edits: Map<Int, String> = emptyMap()) = VendorWork(
        vendor = "claude_code",
        stage = if (final.isEmpty()) VendorStage.DRAFT else VendorStage.FINAL,
        draftLetter = letter,
        finalLetter = final,
        feedback = JsonObject(mapOf("accuracy" to JsonArray(items.toList()))),
        commentsOn = commentsOn,
        paragraphEdits = edits,
    )

    @Test
    fun aQuotedCommentSitsOnItsParagraphHighlightedAndTheRestIsAboutTheWholeLetter() {
        val view = ParagraphReview.of(
            work(
                item("a", "billing migration"),
                item("b", "i enjoy mentoring juniors"), // case and spacing differ from the letter
                item("c", ""),
                item("d", "not in the letter"),
                item("e", "Kotlin", type = "ALREADY_GOOD"),
            ),
        )
        assertEquals(4, view.paragraphs.size)
        val p1 = view.paragraphs[1]
        assertEquals(listOf("a"), p1.comments.map { it.id })
        assertEquals("billing migration", p1.text.substring(p1.comments[0].highlight!!.first, p1.comments[0].highlight!!.last + 1))
        assertEquals(listOf("b"), view.paragraphs[2].comments.map { it.id })
        assertEquals(listOf("c", "d"), view.wholeLetter.map { it.id })
        assertTrue("praise is not something to fix", view.paragraphs.flatMap { it.comments }.none { it.id == "e" })
    }

    @Test
    fun commentsOnAnEarlierVersionShowOnlyTheOpenQuestions() {
        val final = "Dear team,\n\nI moved our billing to Kotlin.\n\nKind regards"
        val view = ParagraphReview.of(
            work(
                item("fix", "billing migration"),
                item("asked", "billing", status = "INPUT_NEEDED"),
                item("answered", "billing", status = "INPUT_NEEDED", answer = "Yes, in 2023"),
                final = final,
                commentsOn = "draft_letter",
            ),
        )
        val shown = view.wholeLetter + view.paragraphs.flatMap { it.comments }
        assertEquals(listOf("asked"), shown.map { it.id })
        assertEquals(1, view.paragraphs.indexOfFirst { p -> p.comments.any { it.id == "asked" } })
    }

    @Test
    fun commentsOnTheFinalVersionAllShow() {
        val final = "Dear team,\n\nI moved our billing to Kotlin.\n\nKind regards"
        val view = ParagraphReview.of(work(item("fix", "moved our billing"), final = final, commentsOn = "final_letter"))
        assertEquals(listOf("fix"), view.paragraphs[1].comments.map { it.id })
    }

    @Test
    fun aRedraftedParagraphTakesTheNewTextAndDropsTheCommentsItAddressed() {
        val view = ParagraphReview.of(work(item("a", "billing migration"), item("b", "mentoring"), edits = mapOf(1 to "I rebuilt billing.")))
        assertEquals("I rebuilt billing.", view.paragraphs[1].text)
        assertTrue(view.paragraphs[1].redrafted && view.paragraphs[1].comments.isEmpty())
        assertEquals(listOf("b"), view.paragraphs[2].comments.map { it.id })
        assertTrue("an addressed comment does not move to the whole letter", view.wholeLetter.isEmpty())
    }

    @Test
    fun regenerateFeedbackPutsTheUsersTextFirst() {
        val notes = listOf(buildJsonObject { put("observation", "Too vague"); put("topic", "precision"); put("quote", "billing") })
        assertEquals("Name the system.\n- [precision] Too vague (about: \"billing\")", LetterGeneration.regenerateFeedback("Name the system.", notes))
    }
}
