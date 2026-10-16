package io.github.fdondi.letterwriter.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.Json as KJson

object Json {
    val codec: KJson = KJson {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
    }

    fun parse(text: String): JsonElement = codec.parseToJsonElement(text)

    /**
     * Python `json.dumps` byte for byte: default separators `", "`/`": "`
     * (or `","`/`": "` with an indent), `ensure_ascii` escaping, key order kept.
     */
    fun pyDumps(
        value: JsonElement,
        indent: Int? = null,
        ensureAscii: Boolean = true,
        itemSeparator: String? = null,
        keySeparator: String? = null,
        sortKeys: Boolean = false,
    ): String {
        val item = itemSeparator ?: if (indent != null) "," else ", "
        val key = keySeparator ?: ": "
        val sb = StringBuilder()
        writePy(sb, value, indent, 0, ensureAscii, item, key, sortKeys)
        return sb.toString()
    }

    private fun writePy(
        sb: StringBuilder,
        v: JsonElement,
        indent: Int?,
        level: Int,
        ascii: Boolean,
        item: String,
        key: String,
        sortKeys: Boolean,
    ) {
        when (v) {
            is JsonNull -> sb.append("null")
            is JsonPrimitive ->
                if (v.isString) writePyString(sb, v.content, ascii) else sb.append(v.content)
            is JsonArray -> {
                if (v.isEmpty()) {
                    sb.append("[]")
                    return
                }
                sb.append('[')
                v.forEachIndexed { i, e ->
                    if (i > 0) sb.append(item)
                    newline(sb, indent, level + 1)
                    writePy(sb, e, indent, level + 1, ascii, item, key, sortKeys)
                }
                newline(sb, indent, level)
                sb.append(']')
            }
            is JsonObject -> {
                if (v.isEmpty()) {
                    sb.append("{}")
                    return
                }
                sb.append('{')
                val entries = if (sortKeys) v.entries.sortedBy { it.key } else v.entries
                entries.forEachIndexed { i, (k, e) ->
                    if (i > 0) sb.append(item)
                    newline(sb, indent, level + 1)
                    writePyString(sb, k, ascii)
                    sb.append(key)
                    writePy(sb, e, indent, level + 1, ascii, item, key, sortKeys)
                }
                newline(sb, indent, level)
                sb.append('}')
            }
        }
    }

    private fun newline(sb: StringBuilder, indent: Int?, level: Int) {
        if (indent == null) return
        sb.append('\n')
        repeat(indent * level) { sb.append(' ') }
    }

    private fun writePyString(sb: StringBuilder, s: String, ascii: Boolean) {
        sb.append('"')
        for (ch in s) {
            when (ch) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                '\b' -> sb.append("\\b")
                '\u000C' -> sb.append("\\f")
                else ->
                    if (ch.code < 0x20 || (ascii && ch.code > 0x7E)) {
                        sb.append("\\u").append(ch.code.toString(16).padStart(4, '0'))
                    } else {
                        sb.append(ch)
                    }
            }
        }
        sb.append('"')
    }
}

/** Python `str(value)` for a parsed JSON value (`None`, `True`, `5`, `5.0`, text). */
fun JsonElement?.pyStr(): String =
    when (this) {
        null, is JsonNull -> "None"
        is JsonPrimitive ->
            if (isString) {
                content
            } else {
                when (booleanOrNull) {
                    true -> "True"
                    false -> "False"
                    null -> content
                }
            }
        else -> Json.pyDumps(this)
    }

/** Python `str(d.get(key) or "")`: falsy values become the empty string. */
fun JsonObject.textOrEmpty(key: String): String {
    val v = this[key] ?: return ""
    return if (v.isPyFalsy()) "" else v.pyStr()
}

fun JsonElement?.isPyFalsy(): Boolean =
    when (this) {
        null, is JsonNull -> true
        is JsonPrimitive ->
            if (isString) {
                content.isEmpty()
            } else {
                booleanOrNull == false || doubleOrNull == 0.0
            }
        is JsonArray -> isEmpty()
        is JsonObject -> isEmpty()
    }

fun JsonElement?.asObjectOrNull(): JsonObject? = this as? JsonObject

fun JsonElement?.asArrayOrNull(): JsonArray? = this as? JsonArray

fun JsonElement?.asStringOrNull(): String? = (this as? JsonPrimitive)?.takeIf { it.isString }?.content

fun JsonElement?.asLongOrNull(): Long? = (this as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull

fun JsonElement?.asDoubleOrNull(): Double? = (this as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull

fun JsonElement?.asBooleanOrNull(): Boolean? = (this as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
