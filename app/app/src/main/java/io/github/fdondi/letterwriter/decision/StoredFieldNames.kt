package io.github.fdondi.letterwriter.decision

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Firestore documents shared with the desktop (feedback snapshots, saved RAG picks)
 * store decision-model fields under their historical `laya_*` names, and
 * `score_source` as `"laya"`. Everything else in the app uses `decision_*`.
 * Convert only when writing to or reading from Firestore.
 */
object StoredFieldNames {
    private const val INTERNAL_PREFIX = "decision_"
    private const val STORED_PREFIX = "laya_"
    private const val SCORE_SOURCE = "score_source"
    private const val STORED_SOURCE = "laya"

    fun toStored(e: JsonElement): JsonElement = rename(e, INTERNAL_PREFIX, STORED_PREFIX, RagJudgement.SOURCE_DECISION_MODEL, STORED_SOURCE)

    fun fromStored(e: JsonElement): JsonElement = rename(e, STORED_PREFIX, INTERNAL_PREFIX, STORED_SOURCE, RagJudgement.SOURCE_DECISION_MODEL)

    private fun rename(e: JsonElement, from: String, to: String, sourceFrom: String, sourceTo: String): JsonElement = when (e) {
        is JsonObject -> JsonObject(
            e.entries.associate { (k, v) ->
                val key = if (k.startsWith(from)) to + k.removePrefix(from) else k
                val value = if (k == SCORE_SOURCE && v is JsonPrimitive && v.isString && v.content == sourceFrom) {
                    JsonPrimitive(sourceTo)
                } else {
                    rename(v, from, to, sourceFrom, sourceTo)
                }
                key to value
            },
        )
        is JsonArray -> JsonArray(e.map { rename(it, from, to, sourceFrom, sourceTo) })
        else -> e
    }
}
