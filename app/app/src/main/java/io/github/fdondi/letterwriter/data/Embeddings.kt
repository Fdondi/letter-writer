package io.github.fdondi.letterwriter.data

import com.google.firebase.firestore.VectorValue
import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.math.sqrt

/** Text to vectors for similar-letter search and quote matching. Tests use a deterministic fake. */
interface EmbeddingService {
    suspend fun embedBatch(texts: List<String>): List<DoubleArray>
}

suspend fun EmbeddingService.embed(text: String): DoubleArray = embedBatch(listOf(text)).first()

/**
 * OpenAI `text-embedding-3-small`, as `vector_store.embed_batch`.
 * The desktop does not record embedding spend in the cost table; neither does the phone.
 */
class Embeddings(private val apiKey: () -> String) : EmbeddingService {
    override suspend fun embedBatch(texts: List<String>): List<DoubleArray> {
        if (texts.isEmpty()) return emptyList()
        val body = buildJsonObject {
            put("model", MODEL)
            put("input", buildJsonArray { texts.forEach { t -> add(JsonPrimitive(if (t.isBlank()) " " else t)) } })
        }
        val resp = Http.postJson("OpenAI embeddings", URL, body, mapOf("Authorization" to "Bearer ${apiKey()}"))
            .asObjectOrNull() ?: throw IllegalStateException("OpenAI embeddings returned a non-object response")
        val rows = resp["data"].asArrayOrNull().orEmpty().mapNotNull { it.asObjectOrNull() }
            .sortedBy { it["index"].asLongOrNull() ?: 0 }
        if (rows.size != texts.size) {
            throw IllegalStateException("OpenAI embeddings returned ${rows.size} vectors for ${texts.size} inputs")
        }
        return rows.map { r ->
            r["embedding"].asArrayOrNull().orEmpty().map { it.asDoubleOrNull() ?: 0.0 }.toDoubleArray()
        }
    }

    companion object {
        const val MODEL = "text-embedding-3-small"
        private const val URL = "https://api.openai.com/v1/embeddings"

        /** Firestore `Vector` fields, or plain number arrays (the desktop stores alias vectors that way). */
        fun vectorOf(raw: Any?): DoubleArray? = when (raw) {
            is VectorValue -> raw.toArray()
            is DoubleArray -> raw
            is List<*> -> raw.map { (it as? Number)?.toDouble() ?: return null }.toDoubleArray()
            else -> null
        }

        /** Cosine similarity; Firestore's COSINE `find_nearest` orders by 1 - this. */
        fun cosine(a: DoubleArray, b: DoubleArray): Double {
            if (a.size != b.size || a.isEmpty()) return Double.NaN
            var dot = 0.0
            var na = 0.0
            var nb = 0.0
            for (i in a.indices) {
                dot += a[i] * b[i]
                na += a[i] * a[i]
                nb += b[i] * b[i]
            }
            if (na == 0.0 || nb == 0.0) return Double.NaN
            return dot / (sqrt(na) * sqrt(nb))
        }
    }
}
