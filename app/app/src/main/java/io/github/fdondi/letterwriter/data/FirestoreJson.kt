package io.github.fdondi.letterwriter.data

import com.google.firebase.Timestamp
import com.google.firebase.firestore.Blob
import com.google.firebase.firestore.DocumentReference
import com.google.firebase.firestore.GeoPoint
import com.google.firebase.firestore.VectorValue
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Instant

/**
 * Firestore values <-> JSON, so the ported Python logic can work on one representation.
 * Timestamps become ISO-8601 strings (sortable like Python datetimes); vectors become number arrays.
 */
object FirestoreJson {
    fun toJson(value: Any?): JsonElement =
        when (value) {
            null -> JsonNull
            is String -> JsonPrimitive(value)
            is Boolean -> JsonPrimitive(value)
            is Long -> JsonPrimitive(value)
            is Int -> JsonPrimitive(value)
            is Double -> JsonPrimitive(value)
            is Float -> JsonPrimitive(value)
            is Timestamp -> JsonPrimitive(Instant.ofEpochSecond(value.seconds, value.nanoseconds.toLong()).toString())
            is VectorValue -> JsonArray(value.toArray().map { JsonPrimitive(it) })
            is Map<*, *> -> JsonObject(value.entries.associate { (k, v) -> k.toString() to toJson(v) })
            is List<*> -> JsonArray(value.map { toJson(it) })
            is DocumentReference -> JsonPrimitive(value.path)
            is GeoPoint -> JsonPrimitive("${value.latitude},${value.longitude}")
            is Blob -> JsonPrimitive("<blob ${value.toBytes().size} bytes>")
            else -> JsonPrimitive(value.toString())
        }

    fun toJsonObject(data: Map<String, Any?>?): JsonObject =
        if (data == null) JsonObject(emptyMap()) else toJson(data) as JsonObject

    /** JSON -> Firestore write value. Nested arrays become JSON strings, like Python `_firestore_safe_value`. */
    fun toFirestore(value: JsonElement?): Any? =
        when (value) {
            null, is JsonNull -> null
            is JsonPrimitive -> when {
                value.isString -> value.content
                value.asBooleanOrNull() != null -> value.booleanOrNull
                value.longOrNull != null -> value.longOrNull
                else -> value.doubleOrNull?.takeIf { it.isFinite() }
            }
            is JsonObject -> value.mapValues { toFirestore(it.value) }
            is JsonArray -> value.map { item ->
                if (item is JsonArray) {
                    Json.pyDumps(item, ensureAscii = false)
                } else {
                    toFirestore(item)
                }
            }
        }
}
