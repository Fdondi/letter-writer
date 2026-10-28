package io.github.fdondi.letterwriter.data

import io.github.fdondi.letterwriter.core.Http
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.jsoup.Jsoup
import org.jsoup.nodes.Element
import org.jsoup.nodes.Node
import org.jsoup.nodes.TextNode
import org.jsoup.select.NodeTraversor
import org.jsoup.select.NodeVisitor

/**
 * Turns a shared job-post URL into plain text for the intake screen.
 * The desktop gets the page from its browser extension; the phone downloads it,
 * so pages that need a login or render with JavaScript come back empty and say so.
 */
object JobPageFetcher {
    private val URL_ONLY = Regex("^https?://\\S+$")
    private val URL_ANYWHERE = Regex("https?://\\S+")
    private val BLOCK_TAGS = setOf(
        "p", "div", "section", "article", "li", "ul", "ol", "br", "tr", "table",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "main", "dd", "dt",
    )

    data class Page(val url: String, val title: String, val text: String)

    /** The URL when the shared text is just a link (share sheets often add a title line before it). */
    fun urlIn(shared: String): String? {
        val t = shared.trim()
        if (URL_ONLY.matches(t)) return t
        val lines = t.lines().map { it.trim() }.filter { it.isNotEmpty() }
        if (lines.size <= 2) return URL_ANYWHERE.find(t)?.value
        return null
    }

    suspend fun fetch(url: String): Page {
        val html = Http.getText("Job page", url, mapOf("User-Agent" to "Mozilla/5.0 (Android) LetterWriter"))
        // Parsing a large page takes long enough to stutter the UI; keep it off the main thread.
        return withContext(Dispatchers.Default) { parse(url, html) }
    }

    private fun parse(url: String, html: String): Page {
        val doc = Jsoup.parse(html, url)
        doc.select("script, style, noscript, nav, footer, svg, form, iframe").remove()
        val text = blockText(doc.body())
        if (text.isBlank()) {
            throw IllegalStateException("The page at $url has no readable text (it may need a login or JavaScript). Paste the job text instead.")
        }
        return Page(url, doc.title().trim(), text)
    }

    private fun blockText(root: Element): String {
        val sb = StringBuilder()
        NodeTraversor.traverse(object : NodeVisitor {
            override fun head(node: Node, depth: Int) {
                when (node) {
                    is TextNode -> sb.append(node.text())
                    is Element -> if (node.normalName() in BLOCK_TAGS) sb.append('\n')
                }
            }

            override fun tail(node: Node, depth: Int) {
                if (node is Element && node.normalName() in BLOCK_TAGS) sb.append('\n')
            }
        }, root)
        return sb.toString()
            .lines()
            .map { it.replace(Regex("[ \\t\\u00A0]+"), " ").trim() }
            .fold(ArrayList<String>()) { acc, line ->
                if (line.isEmpty() && (acc.isEmpty() || acc.last().isEmpty())) acc else acc.apply { add(line) }
            }
            .joinToString("\n")
            .trim()
    }
}
