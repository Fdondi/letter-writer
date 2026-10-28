package io.github.fdondi.letterwriter.data

import java.net.URI
import java.security.MessageDigest

/**
 * `canonical_key` and document ids of `opportunities` (OPPORTUNITY_PIPELINE_PLAN.md §3, §4.3).
 * The desktop batch must produce the same strings, so every rule here is spelled out in the plan.
 */
object OpportunityKeys {
    /** Query parameters dropped from stored URLs and `url:` keys (compared lowercase; `utm_*` by prefix). */
    val TRACKING_PARAMS = setOf("source", "uid", "mid", "trk", "refid", "trackingid", "gclid", "fbclid")

    private val UUID_IN_PATH = Regex("([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
    private val LINKEDIN_VIEW = Regex("/jobs/view/(?:[^/]*?-)?(\\d+)(?:/|$)")
    private val SWISSDEVJOBS_PATH = Regex("^/jobs/([^/]+)")
    private val JOBCLOUD_HOSTS = setOf("jobs.ch", "jobup.ch", "jobscout24.ch")

    /**
     * jobs.ch, jobup.ch and JobScout24 share vacancy UUIDs (`jobs.ch:<uuid>`); LinkedIn by job id;
     * swissdevjobs by slug; anything else `url:` + scheme, host, path and non-tracking parameters, lowercased.
     */
    fun canonicalKey(rawUrl: String): String {
        val url = rawUrl.trim()
        val uri = parse(url) ?: return "url:" + url.lowercase()
        val host = host(uri)
        val path = uri.rawPath.orEmpty()
        val params = queryParams(uri)
        if (JOBCLOUD_HOSTS.any { host == it || host.endsWith(".$it") }) {
            UUID_IN_PATH.find(path.lowercase())?.let { return "jobs.ch:${it.groupValues[1]}" }
        }
        if (host == "linkedin.com" || host.endsWith(".linkedin.com")) {
            LINKEDIN_VIEW.find(path)?.let { return "linkedin:${it.groupValues[1]}" }
            params.firstOrNull { it.first.equals("currentJobId", ignoreCase = true) && it.second.all(Char::isDigit) && it.second.isNotEmpty() }
                ?.let { return "linkedin:${it.second}" }
        }
        if (host == "swissdevjobs.ch" || host.endsWith(".swissdevjobs.ch")) {
            SWISSDEVJOBS_PATH.find(path)?.let { return "swissdevjobs:${it.groupValues[1].lowercase()}" }
        }
        return "url:" + normalizedUrl(uri, host).lowercase()
    }

    /** Key for a posting shared as text with no link: `text:` + sha256 of its whitespace-collapsed text, 16 hex chars. */
    fun textKey(text: String): String =
        "text:" + sha256(text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")).take(16)

    /** `opportunities` document id: sha256 of `"<user_id>\n<canonical_key>"`, first 32 hex chars. */
    fun documentId(userId: String, canonicalKey: String): String = sha256("$userId\n$canonicalKey").take(32)

    /** `source` field for a key: jobs.ch, linkedin, swissdevjobs, or manual. */
    fun sourceOf(canonicalKey: String): String = when (canonicalKey.substringBefore(":")) {
        "jobs.ch" -> "jobs.ch"
        "linkedin" -> "linkedin"
        "swissdevjobs" -> "swissdevjobs"
        else -> "manual"
    }

    /** The URL as stored on the opportunity: tracking parameters and fragment removed, case kept. */
    fun cleanUrl(rawUrl: String): String {
        val url = rawUrl.trim()
        val uri = parse(url) ?: return url
        return normalizedUrl(uri, uri.host.orEmpty())
    }

    private fun normalizedUrl(uri: URI, host: String): String {
        val scheme = (uri.scheme ?: "https").lowercase()
        var path = uri.rawPath.orEmpty()
        if (path.length > 1) path = path.trimEnd('/')
        val kept = queryParams(uri).filter { (k, _) -> !isTracking(k) }.sortedWith(compareBy({ it.first }, { it.second }))
        val query = if (kept.isEmpty()) "" else "?" + kept.joinToString("&") { (k, v) -> if (v.isEmpty()) k else "$k=$v" }
        val port = if (uri.port > 0) ":${uri.port}" else ""
        return "$scheme://$host$port$path$query"
    }

    private fun isTracking(name: String): Boolean {
        val n = name.lowercase()
        return n.startsWith("utm_") || n in TRACKING_PARAMS
    }

    private fun parse(url: String): URI? {
        val uri = runCatching { URI(url) }.getOrNull() ?: return null
        if (uri.scheme == null || uri.host.isNullOrEmpty()) return null
        return uri
    }

    private fun host(uri: URI): String = uri.host.orEmpty().lowercase().removePrefix("www.")

    /** Raw (still percent-encoded) name/value pairs, so a cleaned URL stays valid. */
    private fun queryParams(uri: URI): List<Pair<String, String>> =
        uri.rawQuery.orEmpty().split("&").filter { it.isNotEmpty() }.map { part ->
            part.substringBefore("=") to (if ("=" in part) part.substringAfter("=") else "")
        }

    private fun sha256(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}
