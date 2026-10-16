package io.github.fdondi.letterwriter

import io.github.fdondi.letterwriter.core.FileSharedAssets
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.llm.AnthropicClient
import io.github.fdondi.letterwriter.llm.Catalogs
import io.github.fdondi.letterwriter.llm.DeepSeekClient
import io.github.fdondi.letterwriter.llm.GeminiClient
import io.github.fdondi.letterwriter.llm.GrokClient
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.MistralClient
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.llm.OpenAiClient
import io.github.fdondi.letterwriter.llm.RoleRef
import io.github.fdondi.letterwriter.llm.UsageCollector
import io.github.fdondi.letterwriter.llm.withUsagePhase
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.double
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import kotlin.math.abs

/**
 * Prices the cases in `letter_writer/prompts/golden/costs.json` (written by
 * `scripts/costs/capture_cost_golden.py` with the desktop clients' `track_cost`)
 * by sending each vendor's REST usage payload through the phone's client.
 */
class CostParityTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val catalogs = Catalogs(FileSharedAssets(repoRoot))
    private val cases = Json.parse(repoRoot.resolve("letter_writer/prompts/golden/costs.json").readText())
        .jsonObject["cases"]!!.jsonArray.map { it.jsonObject }
    private lateinit var server: MockWebServer

    @Before
    fun start() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun stop() {
        server.shutdown()
    }

    private fun JsonObject.n(key: String): Long = this[key]?.jsonPrimitive?.long ?: 0

    private fun client(vendor: String): LlmClient {
        val base = server.url("/").toString().trimEnd('/')
        val v = ModelVendor.fromKey(vendor) ?: error("unknown vendor $vendor")
        val catalog = catalogs[v]
        return when (v) {
            ModelVendor.OPENAI -> OpenAiClient(catalog, emptyMap(), "test", base)
            ModelVendor.ANTHROPIC -> AnthropicClient(catalog, emptyMap(), "test", base)
            ModelVendor.GEMINI -> GeminiClient(catalog, emptyMap(), "test", base)
            ModelVendor.MISTRAL -> MistralClient(catalog, emptyMap(), "test", base)
            ModelVendor.GROK -> GrokClient(catalog, emptyMap(), "test", base)
            ModelVendor.DEEPSEEK -> DeepSeekClient(catalog, emptyMap(), "test", base)
        }
    }

    /** The usage block each vendor's REST API returns for these counts. */
    private fun responseBody(c: JsonObject): String {
        val input = c.n("input")
        val output = c.n("output")
        val cached = c.n("cached")
        return when (c["vendor"]!!.jsonPrimitive.content) {
            "openai" -> """{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":$input,"completion_tokens":$output,"prompt_tokens_details":{"cached_tokens":$cached,"cache_write_tokens":${c.n("cache_write")}}}}"""
            "anthropic" -> """{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":$input,"output_tokens":$output,"cache_read_input_tokens":${c.n("cache_read")},"cache_creation_input_tokens":${c.n("cache_write")}}}"""
            "gemini" -> {
                val queries = (1..c.n("search")).joinToString(",") { "\"q$it\"" }
                """{"candidates":[{"content":{"parts":[{"text":"ok"}]},"groundingMetadata":{"webSearchQueries":[$queries]}}],"usageMetadata":{"promptTokenCount":$input,"candidatesTokenCount":$output,"cachedContentTokenCount":$cached}}"""
            }
            "mistral" -> """{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":$input,"completion_tokens":$output}}"""
            "grok" -> """{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":$input,"completion_tokens":$output,"prompt_tokens_details":{"cached_tokens":$cached}}}"""
            "deepseek" -> """{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":$input,"completion_tokens":$output,"prompt_cache_hit_tokens":$cached}}"""
            else -> error("no payload for ${c["vendor"]}")
        }
    }

    @Test
    fun phoneCostsMatchDesktopTrackCost() {
        assertTrue("no cost cases found", cases.isNotEmpty())
        val mismatches = ArrayList<String>()
        for (c in cases) {
            val id = c["id"]!!.jsonPrimitive.content
            val vendor = c["vendor"]!!.jsonPrimitive.content
            val model = c["model"]!!.jsonPrimitive.content
            val want = c["expected_cost"]!!.jsonPrimitive.double
            server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody(responseBody(c)))
            val collector = UsageCollector("test")
            runBlocking {
                withUsagePhase(collector) {
                    client(vendor).call(RoleRef.ModelId(model), "system", listOf("user"), search = c.n("search") > 0)
                }
            }
            val got = collector.totals().values.sumOf { it.cost }
            if (abs(got - want) > 1e-12) mismatches += "$id ($vendor/$model): desktop $want, phone $got"
            if (want == 0.0) assertEquals("$id should be reported as unpriced", listOf("$vendor/$model"), collector.unpricedModels())
        }
        assertEquals("Phone costs differ from desktop:\n" + mismatches.joinToString("\n"), 0, mismatches.size)
    }
}
