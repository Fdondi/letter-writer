package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.pyStr
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/** Model output that should have been JSON but was not; the message carries the start of the raw text. */
class ModelOutputException(message: String, cause: Throwable? = null) : IllegalArgumentException(message, cause)

/** Python helpers that read JSON out of model replies. */
object ModelOutput {
    /** `_extract_json_value`: tolerates a ```json fence; throws on empty or invalid text. */
    fun extractJsonValue(raw: String): JsonElement {
        var text = raw.trim()
        if (text.isEmpty()) throw ModelOutputException("empty model reply")
        text = unfence(text)
        return try {
            Json.parse(text)
        } catch (e: SerializationException) {
            throw ModelOutputException("reply is not JSON: ${preview(raw)}", e)
        } catch (e: IllegalArgumentException) {
            throw ModelOutputException("reply is not JSON: ${preview(raw)}", e)
        }
    }

    /** `_loads_extraction_json` / `_extract_json_object`: an object, or null when nothing parses. */
    fun loadsObjectOrNull(raw: String, allowEmbedded: Boolean): JsonObject? {
        var text = raw.trim()
        if (text.isEmpty()) return null
        text = unfence(text)
        parseOrNull(text)?.let { return it as? JsonObject }
        if (!allowEmbedded) return null
        val start = text.indexOf('{')
        val end = text.lastIndexOf('}')
        if (start >= 0 && end > start) return parseOrNull(text.substring(start, end + 1)) as? JsonObject
        return null
    }

    /** Python bare `json.loads(raw)` into a dict; null when it is not a JSON object. */
    fun strictObjectOrNull(raw: String): JsonObject? = parseOrNull(raw) as? JsonObject

    fun preview(raw: String, max: Int = 300): String {
        val t = raw.trim()
        return if (t.length <= max) t else t.take(max) + "…"
    }

    private fun parseOrNull(text: String): JsonElement? =
        try {
            Json.parse(text)
        } catch (_: SerializationException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }

    private fun unfence(text: String): String {
        if (!text.startsWith("```")) return text
        val lines = text.split("\n")
        var inner = (if (lines.size > 2) lines.subList(1, lines.size - 1) else lines).joinToString("\n").trim()
        if (inner.lowercase().startsWith("json")) inner = inner.substring(4).trimStart()
        return inner
    }
}

/** Python `str(d.get(key, ""))`: a missing key is "", an explicit null is "None". */
fun JsonObject.getStr(key: String): String = if (key in this) this[key].pyStr() else ""

fun JsonElement?.asListOrEmpty(): List<JsonElement> = (this as? JsonArray)?.toList().orEmpty()
