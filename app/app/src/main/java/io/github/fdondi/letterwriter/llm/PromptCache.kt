package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.PyText
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import java.security.MessageDigest

/** Port of `clients/prompt_cache.py` and the shared parts of `openai_prompt_cache.py`. */
object PromptCache {
    private const val PAD_HEADER =
        "\n\n---\n[Prompt-cache padding: no semantic content; satisfies provider minimum cache size.]\n---\n"
    private const val PAD_UNIT = "cachepadding "
    private const val CHARS_PER_TOKEN = 4
    private const val MAX_CACHE_BLOCK_GROWTH = 2.0

    fun estimateTokens(text: String): Int = maxOf(1, PyText.length(text) / CHARS_PER_TOKEN)

    /** Join non-empty static sections into one cacheable prefix. */
    fun combine(vararg parts: String?): String =
        parts.mapNotNull { it?.trim()?.takeIf { s -> s.isNotEmpty() } }.joinToString("\n\n")

    /** (system prefix, user prefix) after merging both into the system side when both are set. */
    fun mergePrefixes(systemCachePrefix: String?, cachePrefix: String?): Pair<String?, String?> {
        val sys = systemCachePrefix?.trim().orEmpty()
        val usr = cachePrefix?.trim().orEmpty()
        return when {
            sys.isNotEmpty() && usr.isNotEmpty() -> combine(sys, usr) to null
            sys.isNotEmpty() -> sys to null
            usr.isNotEmpty() -> null to usr
            else -> null to null
        }
    }

    /** Pad toward [minTokens] when that at most doubles the block; otherwise return it unchanged. */
    fun padCacheBlock(text: String, minTokens: Int): String {
        val body = text.trim()
        if (body.isEmpty()) return text
        val target = minTokens + maxOf(32, minTokens / 25)
        val est = estimateTokens(body)
        if (est >= target) return body
        val maxTotal = (est * MAX_CACHE_BLOCK_GROWTH).toInt()
        if (target > maxTotal) return body
        val needChars = (target - est) * CHARS_PER_TOKEN + PAD_UNIT.length
        val repeat = maxOf(1, (needChars + PAD_UNIT.length - 1) / PAD_UNIT.length)
        return body + PAD_HEADER + PAD_UNIT.repeat(repeat)
    }

    fun prepareCacheBlock(text: String?, minTokens: Int): String? {
        val body = text?.trim().orEmpty()
        if (body.isEmpty()) return null
        return padCacheBlock(body, minTokens)
    }

    /** Stable routing key for requests that share the same cached prefix. */
    fun promptCacheKey(vararg parts: String?): String {
        val md = MessageDigest.getInstance("SHA-256")
        for (part in parts) {
            val text = part?.trim().orEmpty()
            if (text.isEmpty()) continue
            md.update(text.toByteArray(Charsets.UTF_8))
            md.update(0)
        }
        return "letter-writer:" + md.digest().toHex().take(32)
    }

    fun cacheKeyForPrefix(prefix: String?, fallback: String): String {
        val body = prefix?.trim().orEmpty()
        return if (body.isNotEmpty()) promptCacheKey(body) else fallback
    }

    /**
     * Calls sharing a prefix run in order so the provider reuses one cache write;
     * independent prefix groups run concurrently (Python `run_cache_grouped_tasks`).
     */
    suspend fun <T> runCacheGroupedTasks(
        tasks: List<Triple<String, String?, suspend () -> T>>,
        maxParallelGroups: Int = 8,
    ): Map<String, T> = coroutineScope {
        val grouped = LinkedHashMap<String, MutableList<Pair<String, suspend () -> T>>>()
        for ((name, prefix, fn) in tasks) {
            grouped.getOrPut(cacheKeyForPrefix(prefix, "task:$name")) { ArrayList() }.add(name to fn)
        }
        val gate = Semaphore(maxOf(1, minOf(maxParallelGroups, grouped.size)))
        grouped.values
            .map { chain ->
                async {
                    gate.withPermit { chain.map { (name, fn) -> name to fn() } }
                }
            }
            .awaitAll()
            .flatten()
            .toMap()
    }
}

fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
