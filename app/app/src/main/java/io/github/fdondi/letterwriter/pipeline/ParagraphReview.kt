package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.pyStr
import kotlinx.serialization.json.JsonObject

/** One comment placed on the review: the item, its category, and the quoted range in its paragraph. */
data class ReviewComment(val category: String, val item: JsonObject, val highlight: IntRange?) {
    val id: String get() = item["id"].pyStr()
    val isQuestion: Boolean get() = item["status"].pyStr().uppercase() == "INPUT_NEEDED"
}

data class ReviewParagraph(val index: Int, val text: String, val comments: List<ReviewComment>, val redrafted: Boolean)

/** A vendor's letter as the paragraph review shows it. */
data class ParagraphView(val paragraphs: List<ReviewParagraph>, val wholeLetter: List<ReviewComment>)

/**
 * Paragraph-style review of one vendor's letter: each comment sits on the paragraph that holds
 * its quote (highlighted there), comments without a quote apply to the whole letter, and nothing
 * blocks: a paragraph can be used as it is or redrafted with the comments the user picks.
 */
object ParagraphReview {
    fun of(w: VendorWork): ParagraphView {
        val paragraphs = w.reviewParagraphs()
        // Comments were made on the paragraphs as they came; a redrafted one no longer holds its quote.
        val original = LetterGeneration.splitParagraphs(w.reviewText)
        val onParagraph = paragraphs.indices.associateWith { ArrayList<ReviewComment>() }
        val wholeLetter = ArrayList<ReviewComment>()
        for (cat in FeedbackItems.CATEGORIES) {
            for (item in w.items(cat)) {
                if (!shown(item, w)) continue
                val quote = item["matched_text"].pyStr().ifBlank { item["quote"].pyStr() }.trim()
                val placed = if (quote.isEmpty()) null else locate(original, quote)
                if (placed == null) {
                    wholeLetter += ReviewComment(cat, item, null)
                } else if (placed.first !in w.paragraphEdits) { // a redraft addressed it
                    onParagraph.getValue(placed.first) += ReviewComment(cat, item, placed.second)
                }
            }
        }
        return ParagraphView(
            paragraphs.mapIndexed { i, text -> ReviewParagraph(i, text, onParagraph.getValue(i), i in w.paragraphEdits) },
            wholeLetter,
        )
    }

    /**
     * Comments to fix, on the text shown. Comments about an earlier version (the desktop rewrote
     * the letter after commenting it) are left out, except questions nobody answered yet: a rewrite
     * can't answer those, so they still matter.
     */
    private fun shown(item: JsonObject, w: VendorWork): Boolean {
        if (item["type"].pyStr() != FeedbackUi.PLEASE_FIX || FeedbackUi.isHidden(item)) return false
        if (w.commentsMatchReview) return true
        val question = item["status"].pyStr().uppercase() == "INPUT_NEEDED"
        return question && item["user_context"].pyStr().isBlank() && item["input_declined"].pyStr() != "True"
    }

    /** The paragraph holding [quote] (exactly, else ignoring case and spacing) and the range there. */
    fun locate(paragraphs: List<String>, quote: String): Pair<Int, IntRange>? {
        for ((i, p) in paragraphs.withIndex()) {
            val span = QuoteSpans.exact(p, quote) ?: QuoteSpans.normalized(p, quote) ?: continue
            return i to (span.first until span.second)
        }
        return null
    }
}
