package io.github.fdondi.letterwriter.llm

import io.github.fdondi.letterwriter.core.FileSharedAssets
import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.HttpStatusException
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.File
import java.io.IOException

/**
 * Every vendor client against a local mock server: the request goes out in the vendor's shape,
 * the reply is parsed and its usage recorded, and broken replies (HTTP errors, a dropped
 * connection, text that is not JSON, JSON with no text) end in an exception, never a hang or an Error.
 */
class VendorClientsHttpTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val catalogs = Catalogs(FileSharedAssets(repoRoot))
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private data class Vendor(val vendor: ModelVendor, val ok: String, val noText: String, val make: (String) -> LlmClient)

    private fun base(path: String) = server.url(path).toString().trimEnd('/')

    private fun vendors(): List<Vendor> {
        val chat = """{"choices":[{"message":{"content":"hello from the mock"}}],"usage":{"prompt_tokens":10,"completion_tokens":5}}"""
        val chatNoText = """{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":0}}"""
        return listOf(
            Vendor(ModelVendor.OPENAI, chat, chatNoText) { OpenAiClient(catalogs[ModelVendor.OPENAI], emptyMap(), "key", base(it)) },
            Vendor(
                ModelVendor.ANTHROPIC,
                """{"content":[{"type":"text","text":"hello from the mock"}],"usage":{"input_tokens":10,"output_tokens":5},"stop_reason":"end_turn"}""",
                """{"content":[],"usage":{"input_tokens":10,"output_tokens":0}}""",
            ) { AnthropicClient(catalogs[ModelVendor.ANTHROPIC], emptyMap(), "key", base(it)) },
            Vendor(
                ModelVendor.GEMINI,
                """{"candidates":[{"content":{"parts":[{"text":"hello from the mock"}]}}],"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5}}""",
                """{"candidates":[{"finishReason":"SAFETY"}],"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":0}}""",
            ) { GeminiClient(catalogs[ModelVendor.GEMINI], emptyMap(), "key", base(it)) },
            Vendor(ModelVendor.MISTRAL, chat, chatNoText) { MistralClient(catalogs[ModelVendor.MISTRAL], emptyMap(), "key", base(it)) },
            Vendor(ModelVendor.GROK, chat, chatNoText) { GrokClient(catalogs[ModelVendor.GROK], emptyMap(), "key", base(it)) },
            Vendor(ModelVendor.DEEPSEEK, chat, chatNoText) { DeepSeekClient(catalogs[ModelVendor.DEEPSEEK], emptyMap(), "key", base(it)) },
        )
    }

    private suspend fun LlmClient.draft(): String {
        val collector = UsageCollector("test")
        return withUsagePhase(collector) { call(ModelRole.LETTER_DRAFT, "system", listOf("write the letter")) }
    }

    /** The call must fail with an ordinary exception within a few seconds. */
    private fun expectFailure(what: String, block: suspend () -> Unit): Exception {
        try {
            runBlocking { withTimeout(15_000) { block() } }
        } catch (e: Exception) {
            return e
        } catch (e: Throwable) {
            fail("$what: expected an exception, got the error $e")
        }
        fail("$what: expected an exception, the call succeeded")
        throw AssertionError()
    }

    @Test
    fun aGoodReplyIsParsedAndItsUsageRecorded() = runBlocking<Unit> {
        for (v in vendors()) {
            server.enqueue(MockResponse().setBody(v.ok).setHeader("Content-Type", "application/json"))
            val collector = UsageCollector("draft")
            val text = withUsagePhase(collector) { v.make("/${v.vendor.key}").call(ModelRole.LETTER_DRAFT, "system", listOf("write the letter")) }
            assertEquals(v.vendor.label, "hello from the mock", text.trim())
            assertEquals(v.vendor.label, 10L, collector.totals().getValue(v.vendor.key).inputTokens)
            val request = server.takeRequest()
            assertTrue(v.vendor.label, request.body.readUtf8().contains("write the letter"))
        }
    }

    @Test
    fun anHttpErrorIsAnException() {
        for (v in vendors()) {
            server.enqueue(MockResponse().setResponseCode(402).setBody("""{"error":{"message":"Your credit balance is too low"}}"""))
            val e = expectFailure("${v.vendor.label} 402") { v.make("/${v.vendor.key}").draft() }
            val status = generateSequence<Throwable>(e) { it.cause }.filterIsInstance<HttpStatusException>().firstOrNull()
            assertEquals("${v.vendor.label}: $e", 402, status?.status)
        }
    }

    @Test
    fun aConnectionDroppedMidReplyFailsInsteadOfHanging() {
        for (v in vendors()) {
            server.enqueue(MockResponse().setBody(v.ok + " ".repeat(64 * 1024)).setSocketPolicy(SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY))
            val e = expectFailure("${v.vendor.label} dropped connection") { v.make("/${v.vendor.key}").draft() }
            assertTrue("${v.vendor.label}: $e", generateSequence<Throwable>(e) { it.cause }.any { it is IOException })
        }
    }

    @Test
    fun aReplyThatIsNotJsonIsAnException() {
        for (v in vendors()) {
            server.enqueue(MockResponse().setBody("<html>Bad gateway</html>"))
            expectFailure("${v.vendor.label} not JSON") { v.make("/${v.vendor.key}").draft() }
        }
    }

    @Test
    fun aReplyWithNoTextIsAnExceptionOrEmpty() {
        for (v in vendors()) {
            server.enqueue(MockResponse().setBody(v.noText))
            // Mistral and Anthropic return "" (the draft step then rejects it); the others throw.
            val outcome = runCatching { runBlocking { withTimeout(15_000) { v.make("/${v.vendor.key}").draft() } } }
            outcome.exceptionOrNull()?.let { assertTrue("${v.vendor.label}: $it", it is Exception) }
            outcome.getOrNull()?.let { assertEquals(v.vendor.label, "", it) }
        }
    }

    @Test
    fun httpGetTextFailsOnAReadErrorToo() {
        server.enqueue(MockResponse().setBody("x".repeat(64 * 1024)).setSocketPolicy(SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY))
        val e = expectFailure("job page") { Http.getText("Job page", server.url("/job").toString()) }
        assertTrue(e.toString(), e is IOException)
        assertTrue(e.message.orEmpty(), e.message.orEmpty().startsWith("Job page"))
    }
}
