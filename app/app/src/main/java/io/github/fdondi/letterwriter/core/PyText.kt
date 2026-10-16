package io.github.fdondi.letterwriter.core

/**
 * String helpers that count Unicode code points the way Python does.
 *
 * Prompt excerpts such as `job_text[:500]` must cut at the same place as the
 * desktop, including for text with emoji or other characters outside the BMP.
 */
object PyText {
    fun length(s: String): Int = s.codePointCount(0, s.length)

    /** Python `s[:n]`. */
    fun take(s: String, n: Int): String {
        if (n <= 0) return ""
        if (n >= length(s)) return s
        return s.substring(0, s.offsetByCodePoints(0, n))
    }

    /** Python `s[start:end]` for non-negative bounds. */
    fun slice(s: String, start: Int, end: Int): String {
        val len = length(s)
        val a = start.coerceIn(0, len)
        val b = end.coerceIn(a, len)
        return s.substring(s.offsetByCodePoints(0, a), s.offsetByCodePoints(0, b))
    }

    /** Python `s.find(sub)`: code point index or -1. */
    fun find(s: String, sub: String): Int {
        val at = s.indexOf(sub)
        return if (at < 0) -1 else s.codePointCount(0, at)
    }

    /** Python `" ".join(s.split())`. */
    fun collapseWhitespace(s: String): String = s.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
}
