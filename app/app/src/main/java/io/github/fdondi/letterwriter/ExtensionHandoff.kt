package io.github.fdondi.letterwriter

import java.net.URLDecoder

/**
 * A page handed over by the browser extension (extensions/job-capture) through the
 * `letterwriter://capture?url=…&text=…` URL scheme. This is the queueing path on browsers without
 * the extension sign-in API (Firefox for Android): there is no app server there to POST to either,
 * so the extension opens the URL and the app queues the job itself.
 *
 * `text` is null when the posting was too big for the URL — the app then downloads the page
 * ([JobPageFetcher]) instead of queueing truncated text.
 */
data class ExtensionHandoff(val url: String, val text: String?)

/**
 * Parses the query string of a `letterwriter://capture` intent (form encoding, like URLSearchParams
 * produces it). Null when the link carries no job page. Pure JVM so plain unit tests cover it.
 */
fun parseExtensionHandoff(query: String?): ExtensionHandoff? {
    if (query.isNullOrEmpty()) return null
    val params = query.removePrefix("?").split("&").mapNotNull { pair ->
        val eq = pair.indexOf('=')
        if (eq < 0) return@mapNotNull null
        decode(pair.substring(0, eq)) to decode(pair.substring(eq + 1))
    }.toMap()
    val url = params["url"]?.trim().orEmpty()
    if (!url.startsWith("https://") && !url.startsWith("http://")) return null
    return ExtensionHandoff(url, params["text"]?.takeIf { it.isNotBlank() })
}

private fun decode(value: String): String = URLDecoder.decode(value, Charsets.UTF_8)
