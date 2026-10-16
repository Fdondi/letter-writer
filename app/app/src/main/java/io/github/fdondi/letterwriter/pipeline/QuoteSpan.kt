package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.data.Embeddings
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Span offsets are UTF-16 indices (what Compose text and the web UI's JavaScript use). */
data class QuoteSpan(val start: Int, val end: Int, val matchedText: String, val score: Double, val method: String)

/**
 * Port of `quote_span.py`: exact substring, then whitespace/case-insensitive,
 * then the closest embedding among sentence and window candidates.
 */
class QuoteSpans(private val embedBatch: suspend (List<String>) -> List<DoubleArray>) {

    /** Failures of the embedding fallback; the desktop only logs them. */
    val failures = ArrayList<String>()

    suspend fun resolve(letter: String, rawQuote: String): QuoteSpan? {
        val quote = rawQuote.trim()
        if (quote.isEmpty() || letter.isBlank()) return null
        exact(letter, quote)?.let { (s, e) -> return QuoteSpan(s, e, letter.substring(s, e), 1.0, "exact") }
        normalized(letter, quote)?.let { (s, e) -> return QuoteSpan(s, e, letter.substring(s, e), 0.99, "normalized") }
        val candidates = candidateSpans(letter, quote)
        if (candidates.isEmpty()) return null
        val texts = listOf(quote) + candidates.map { (s, e) -> letter.substring(s, e) }
        val vectors = try {
            embedBatch(texts)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            failures += "quote span embedding failed: ${e.message}"
            return null
        }
        if (vectors.size != texts.size) {
            failures += "quote span embedding returned ${vectors.size} vectors for ${texts.size} texts"
            return null
        }
        val q = vectors[0]
        var bestI = 0
        var best = -1.0
        for (i in 1 until vectors.size) {
            val score = Embeddings.cosine(q, vectors[i]).let { if (it.isNaN()) 0.0 else it }
            if (score > best) {
                best = score
                bestI = i - 1
            }
        }
        val (s, e) = candidates[bestI]
        return QuoteSpan(s, e, letter.substring(s, e), best, "vector")
    }

    /** `attach_quote_spans_to_feedback`: sets `matched_text` and `span_start`/`span_end` on every item. */
    suspend fun attachToFeedback(feedback: Map<String, List<JsonObject>>, letter: String): LinkedHashMap<String, List<JsonObject>> {
        val out = LinkedHashMap<String, List<JsonObject>>()
        for ((cat, items) in feedback) {
            out[cat] = items.map { attach(it, letter) }
        }
        return out
    }

    private suspend fun attach(item: JsonObject, letter: String): JsonObject {
        val quote = item.textOrEmpty("quote").trim()
        val m = item.toMutableMap<String, JsonElement>()
        m["quote"] = JsonPrimitive(quote)
        val span = if (quote.isEmpty()) null else resolve(letter, quote)
        if (span == null) {
            m["matched_text"] = JsonPrimitive("")
            m.remove("span_start")
            m.remove("span_end")
        } else {
            m["matched_text"] = JsonPrimitive(span.matchedText)
            m["span_start"] = JsonPrimitive(span.start)
            m["span_end"] = JsonPrimitive(span.end)
        }
        return JsonObject(m)
    }

    companion object {
        private const val MAX_CANDIDATES = 80
        // Same pattern as quote_span.py. Android's regex engine rejects the Java-only (?U) flag,
        // and that failure is an ExceptionInInitializerError, which kills the process.
        private val SENTENCE_SPLIT = Regex("(?<=[.!?])\\s+|\\n+")

        fun exact(letter: String, quote: String): Pair<Int, Int>? {
            if (quote.isEmpty()) return null
            val i = letter.indexOf(quote)
            return if (i >= 0) i to i + quote.length else null
        }

        /** Lowercase collapsed-whitespace text plus the original index of every output char. */
        private fun normalizeWithMap(text: String): Pair<String, IntArray> {
            val out = StringBuilder()
            val map = ArrayList<Int>()
            var prevSpace = true
            text.forEachIndexed { i, ch ->
                if (ch.isWhitespace()) {
                    if (!prevSpace) {
                        out.append(' ')
                        map += i
                        prevSpace = true
                    }
                    return@forEachIndexed
                }
                out.append(ch.lowercaseChar())
                map += i
                prevSpace = false
            }
            if (out.isNotEmpty() && out.last() == ' ') {
                out.setLength(out.length - 1)
                map.removeAt(map.size - 1)
            }
            return out.toString() to map.toIntArray()
        }

        fun normalized(letter: String, quote: String): Pair<Int, Int>? {
            if (quote.isEmpty() || letter.isEmpty()) return null
            val (ln, lmap) = normalizeWithMap(letter)
            val (qn, _) = normalizeWithMap(quote)
            if (qn.isEmpty() || ln.isEmpty()) return null
            val i = ln.indexOf(qn)
            if (i < 0) return null
            return lmap[i] to lmap[i + qn.length - 1] + 1
        }

        private fun sentenceSpans(letter: String): List<Pair<Int, Int>> {
            val parts = SENTENCE_SPLIT.split(letter)
            if (parts.size <= 1) {
                val stripped = letter.trim()
                if (stripped.isEmpty()) return emptyList()
                val start = letter.indexOf(stripped)
                return if (start >= 0) listOf(start to start + stripped.length) else emptyList()
            }
            val spans = ArrayList<Pair<Int, Int>>()
            var from = 0
            for (part in parts) {
                if (part.isBlank()) continue
                var start = letter.indexOf(part, from)
                if (start < 0) start = from
                val end = start + part.length
                spans += start to end
                from = end
            }
            return spans
        }

        private fun windowSpans(letter: String, quoteLen: Int): List<Pair<Int, Int>> {
            val n = letter.length
            if (n == 0 || quoteLen <= 0) return emptyList()
            val sizes = sortedSetOf(maxOf(8, quoteLen), maxOf(8, (quoteLen * 0.75).toInt()), maxOf(8, (quoteLen * 1.25).toInt()))
            val spans = ArrayList<Pair<Int, Int>>()
            val seen = HashSet<Pair<Int, Int>>()
            for (raw in sizes) {
                val size = minOf(raw, n)
                val stride = maxOf(4, size / 2)
                var start = 0
                while (start <= n - size) {
                    val key = start to start + size
                    if (seen.add(key)) spans += key
                    start += stride
                }
                val last = (n - size) to n
                if (seen.add(last)) spans += last
            }
            return spans
        }

        fun candidateSpans(letter: String, quote: String): List<Pair<Int, Int>> {
            val qlen = maxOf(8, quote.trim().length)
            val unique = ArrayList<Pair<Int, Int>>()
            val seen = HashSet<Pair<Int, Int>>()
            for (span in sentenceSpans(letter) + windowSpans(letter, qlen)) {
                if (span.second <= span.first) continue
                if (!seen.add(span)) continue
                unique += span
                if (unique.size >= MAX_CANDIDATES) break
            }
            return unique
        }
    }
}

/** Items of one category as JSON objects, skipping anything else. */
fun JsonElement?.feedbackList(): List<JsonObject> = (this as? JsonArray).orEmpty().filterIsInstance<JsonObject>()
