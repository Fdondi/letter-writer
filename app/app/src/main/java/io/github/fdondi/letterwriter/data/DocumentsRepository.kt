package io.github.fdondi.letterwriter.data

import com.google.firebase.Timestamp
import com.google.firebase.firestore.CollectionReference
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.Query
import com.google.firebase.firestore.SetOptions
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.isPyFalsy
import kotlinx.coroutines.tasks.await
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

/** A previous example as the desktop serializes it (`serialize_document`): no vector, `id` set, ISO dates. */
data class StoredDocument(val id: String, val data: JsonObject) {
    fun text(key: String): String = data[key].asStringOrNull().orEmpty()
    val companyDisplay: String get() = text("company_name_original").ifEmpty { text("company_name") }
}

data class SimilarDocument(val document: StoredDocument, val similarity: Double)

/**
 * Port of the document functions in `firestore_store.py`.
 * Writes use Firestore-native values (Timestamp, vector) so the desktop reads them unchanged.
 */
class DocumentsRepository(
    private val db: () -> FirebaseFirestore,
    private val embeddings: Embeddings,
) {
    private fun documents(): CollectionReference = db().collection("documents")

    suspend fun list(sub: String, limit: Long = 50): List<StoredDocument> =
        documents().whereEqualTo("user_id", sub)
            .orderBy("created_at", Query.Direction.DESCENDING)
            .limit(limit)
            .get().await()
            .documents.map { serialize(it.id, it.data) }

    suspend fun get(sub: String, id: String): StoredDocument? {
        val snap = documents().document(id).get().await()
        if (!snap.exists()) return null
        if (snap.getString("user_id") != sub) throw SecurityException("Document $id belongs to a different user")
        return serialize(snap.id, snap.data)
    }

    suspend fun delete(sub: String, id: String) {
        get(sub, id) ?: return
        documents().document(id).delete().await()
    }

    /**
     * `upsert_document` with `allow_update` (the desktop's create path dedupes by
     * company + role + job text and then merges; update merges by id).
     *
     * Deviation: the desktop's merge writes every field of `base`, so an update that
     * omits blocks/autocomplete/notes resets them. Here an update of an existing
     * document writes only the keys present in [data], plus the derived fields.
     */
    suspend fun upsert(sub: String, data: JsonObject): StoredDocument {
        val now = Timestamp.now()
        val companyRaw = data["company_name"].asStringOrNull()?.takeIf { it.isNotEmpty() }
            ?: data["company"].asStringOrNull()?.takeIf { it.isNotEmpty() }
        val companyName = companyRaw?.trim()?.lowercase()
        val role = data["role"].asStringOrNull()
        val jobText = data["job_text"].asStringOrNull().orEmpty().trim()

        val fingerprint = sha256Hex(
            listOf(sub.trim().lowercase(), companyName.orEmpty(), role.orEmpty().trim().lowercase(), jobText)
                .joinToString("\n"),
        )

        var docId = listOf("id", "document_id", "_id").firstNotNullOfOrNull { data[it].asStringOrNull()?.takeIf(String::isNotEmpty) }
        var existing: Map<String, Any?>? = null
        if (docId == null) {
            val candidates = documents().whereEqualTo("user_id", sub).get().await().documents
            val match = candidates.firstOrNull { c ->
                val cd = c.data.orEmpty()
                val cc = ((cd["company_name_original"] as? String)?.takeIf { it.isNotEmpty() } ?: (cd["company_name"] as? String).orEmpty())
                    .trim().lowercase()
                cc == companyName.orEmpty() &&
                    (cd["role"] as? String).orEmpty().trim().lowercase() == role.orEmpty().trim().lowercase() &&
                    (cd["job_text"] as? String).orEmpty().trim() == jobText
            }
            if (match != null) {
                docId = match.id
                existing = match.data
            }
        } else {
            val snap = documents().document(docId).get().await()
            existing = if (snap.exists()) snap.data else null
        }
        if (existing != null && existing["user_id"] != sub) {
            throw SecurityException("Document $docId belongs to a different user")
        }
        val id = docId ?: UUID.randomUUID().toString()

        val version = if (existing == null) {
            1L
        } else {
            var v = (existing["version"] as? Number)?.toLong() ?: 1L
            val letterChanged = data["letter_text"].asStringOrNull().orEmpty().trim() != (existing["letter_text"] as? String).orEmpty().trim()
            val jobChanged = jobText != (existing["job_text"] as? String).orEmpty().trim()
            if (letterChanged || jobChanged) v += 1
            v
        }

        val derived = mutableMapOf<String, Any?>(
            "user_id" to sub,
            "company_name" to companyName,
            "company_name_original" to companyRaw,
            "application_fingerprint" to fingerprint,
            "version" to version,
            "updated_at" to now,
        )
        val vector = embeddings.embed(jobText)
        derived["vector"] = FieldValue.vector(vector)

        val fields = mutableMapOf<String, Any?>()
        fun put(key: String, value: Any?) {
            if (existing == null || key in data) fields[key] = value
        }
        put("role", role)
        for (k in listOf("location", "language", "salary", "source_url", "date_applied", "notes")) {
            put(k, FirestoreJson.toFirestore(data[k]))
        }
        put("requirements", requirementsValue(data["requirements"]))
        put("job_text", jobText)
        put("letter_text", data["letter_text"].asStringOrNull().orEmpty().trim())
        put(
            "negative_letter_text",
            data["negative_letter_text"].takeUnless { it.isPyFalsy() }?.asStringOrNull()?.trim(),
        )
        put("blocks", FirestoreJson.toFirestore(data["blocks"].takeUnless { it.isPyFalsy() } ?: JsonArray(emptyList())))
        put("autocomplete_sections", prepareAutocompleteSections(data["autocomplete_sections"]))
        put("autocomplete_history", prepareAutocompleteHistory(data["autocomplete_history"]))
        put("ai_letters", prepareAiLetters(data["ai_letters"], now))
        if (existing == null) {
            val createdIso = data["created_at"].asStringOrNull()
            fields["created_at"] = createdIso?.let { parseTimestamp(it) } ?: now
        }

        if ("application_event_log" in data) {
            val incoming = data["application_event_log"]
            when {
                incoming is JsonArray -> {
                    val prior = existing?.get("application_event_log") as? List<*>
                    val incomingFs = FirestoreJson.toFirestore(incoming) as List<*>
                    fields["application_event_log"] = (prior ?: emptyList<Any?>()) + incomingFs
                }
                incoming == null || incoming is JsonNull -> Unit
                else -> throw IllegalArgumentException("application_event_log must be a list when provided")
            }
        }

        val ref = documents().document(id)
        if (existing == null) {
            ref.set(fields + derived).await()
        } else {
            ref.set(fields + derived, SetOptions.merge()).await()
        }
        val stored = ref.get().await()
        return serialize(stored.id, stored.data)
    }

    /** `save_feedback`: one `feedbacks` record per ai_letters entry. */
    suspend fun saveFeedback(sub: String, documentId: String, letterText: String, aiLetters: JsonArray): Int {
        val now = Timestamp.now()
        var saved = 0
        for (entry in aiLetters.mapNotNull { it.asObjectOrNull() }) {
            val corrections = entry["user_corrections"].takeUnless { it.isPyFalsy() } ?: JsonArray(emptyList())
            val chunksUsed = entry["chunks_used"].asLongOrNull() ?: 0L
            val action = when {
                chunksUsed > 0 && !corrections.isPyFalsy() -> "edited"
                chunksUsed > 0 -> "approved"
                else -> "rejected"
            }
            val record = mapOf(
                "user_id" to sub,
                "document_id" to documentId,
                "vendor" to entry["vendor"].asStringOrNull(),
                "model" to entry["model"].asStringOrNull(),
                "action" to action,
                "original_text" to entry["text"].asStringOrNull().orEmpty().trim(),
                "final_text" to letterText.trim(),
                "user_corrections" to FirestoreJson.toFirestore(corrections),
                "chunks_used" to chunksUsed,
                "rating" to FirestoreJson.toFirestore(entry["rating"]),
                "comment" to (entry["comment"].takeUnless { it.isPyFalsy() }?.asStringOrNull() ?: ""),
                "cost" to entry["cost"].asDoubleOrNull(),
                "created_at" to now,
            )
            db().collection("feedbacks").document(UUID.randomUUID().toString()).set(record).await()
            saved++
        }
        return saved
    }

    /** `save_phase_draft_feedback_snapshot`. */
    suspend fun savePhaseDraftFeedbackSnapshot(
        sub: String,
        sessionId: String,
        documentId: String?,
        vendor: String,
        feedback: JsonObject,
        feedbackOverrides: JsonObject?,
    ): String {
        require(sub.isNotEmpty() && sessionId.isNotEmpty() && vendor.isNotEmpty()) { "user_id, session_id, and vendor are required" }
        val safeVendor = vendor.map { if (it.isLetterOrDigit() || it in "._-") it else '_' }.joinToString("").take(200)
        val sid = sessionId.replace("/", "_").take(400)
        val docId = "phase_draft_${sub}_${sid}_$safeVendor".replace("/", "_").take(800)
        val rec = mapOf(
            "user_id" to sub,
            "session_id" to sessionId,
            "document_id" to documentId?.takeIf { it.isNotEmpty() },
            "vendor" to vendor,
            "feedback" to FirestoreJson.toFirestore(feedback),
            "feedback_overrides" to FirestoreJson.toFirestore(feedbackOverrides ?: JsonObject(emptyMap())),
            "updated_at" to Timestamp.now(),
        )
        db().collection("phase_draft_feedback").document(docId).set(rec, SetOptions.merge()).await()
        return docId
    }

    /**
     * Replaces Firestore `find_nearest` (COSINE, limit 7), which the Android SDK lacks:
     * the user's documents are scored on the device. Documents without a vector are skipped.
     */
    suspend fun similar(sub: String, jobText: String, limit: Int = 7): List<SimilarDocument> {
        val query = embeddings.embed(jobText)
        val snaps = documents().whereEqualTo("user_id", sub).get().await().documents
        return snaps.mapNotNull { s ->
            val vec = Embeddings.vectorOf(s.get("vector")) ?: return@mapNotNull null
            val sim = Embeddings.cosine(query, vec)
            if (sim.isNaN()) null else SimilarDocument(serialize(s.id, s.data), sim)
        }.sortedByDescending { it.similarity }.take(limit)
    }

    companion object {
        private fun sha256Hex(text: String): String =
            MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

        fun serialize(id: String, raw: Map<String, Any?>?): StoredDocument {
            val json = FirestoreJson.toJsonObject(raw)
            val out = json.filterKeys { it != "vector" }.toMutableMap()
            out["id"] = JsonPrimitive(id)
            out["ai_letters"] = json["ai_letters"].takeUnless { it.isPyFalsy() } ?: JsonArray(emptyList())
            return StoredDocument(id, JsonObject(out))
        }

        private fun parseTimestamp(iso: String): Timestamp? =
            runCatching { Instant.parse(iso) }.getOrNull()?.let { Timestamp(it.epochSecond, it.nano) }

        private fun requirementsValue(raw: JsonElement?): Any? = when {
            raw is JsonArray -> FirestoreJson.toFirestore(raw)
            raw.isPyFalsy() -> emptyList<Any?>()
            else -> listOf(FirestoreJson.toFirestore(raw))
        }

        private fun str(o: JsonObject, k: String): String =
            o[k].takeUnless { it.isPyFalsy() }?.let { it.asStringOrNull() ?: it.toString() }.orEmpty()

        fun prepareAutocompleteSections(raw: JsonElement?): List<Map<String, Any?>> =
            raw.asArrayOrNull().orEmpty().mapNotNull { it.asObjectOrNull() }.map { sec ->
                listOf("id", "title", "description", "body", "plan", "proposal").associateWith { str(sec, it) }
            }

        fun prepareAutocompleteHistory(raw: JsonElement?): Map<String, Any?>? {
            val h = raw.asObjectOrNull()?.takeIf { it.isNotEmpty() } ?: return null
            val chunks = h["chunks"].asArrayOrNull().orEmpty().mapNotNull { it.asObjectOrNull() }.map { c ->
                val rejectedRaw = c["rejected"]
                val rejected: List<String> = when {
                    rejectedRaw is JsonArray -> rejectedRaw.filter { it !is JsonNull }.map { it.asStringOrNull() ?: it.toString() }
                    rejectedRaw.asStringOrNull()?.isNotEmpty() == true -> listOf(rejectedRaw.asStringOrNull()!!)
                    else -> emptyList()
                }
                mapOf(
                    "text" to str(c, "text"),
                    "accepted" to str(c, "accepted"),
                    "rejected" to rejected,
                    "model" to FirestoreJson.toFirestore(c["model"]),
                    "cost" to c["cost"].asDoubleOrNull()?.takeIf { it.isFinite() },
                )
            }
            val cycle = h["cycle_models"].asArrayOrNull().orEmpty().filter { it !is JsonNull }
                .map { it.asStringOrNull() ?: it.toString() }.filter { it.isNotBlank() }
            return mapOf(
                "fixed_context" to str(h, "fixed_context"),
                "chunks" to chunks,
                "completion_model" to str(h, "completion_model"),
                "plan_model" to str(h, "plan_model"),
                "cycle_models" to cycle,
                "total_cost" to (h["total_cost"].asDoubleOrNull()?.takeIf { it.isFinite() } ?: 0.0),
            )
        }

        /** `_prepare_ai_letters`. */
        fun prepareAiLetters(raw: JsonElement?, now: Timestamp): List<Map<String, Any?>> =
            raw.asArrayOrNull().orEmpty().mapNotNull { it.asObjectOrNull() }.map { l ->
                val created = l["created_at"].asStringOrNull()?.let { parseTimestamp(it) } ?: now
                mapOf(
                    "id" to (l["id"].takeUnless { it.isPyFalsy() }?.asStringOrNull() ?: UUID.randomUUID().toString()),
                    "vendor" to FirestoreJson.toFirestore(l["vendor"]),
                    "model" to FirestoreJson.toFirestore(l["model"]),
                    "text" to l["text"].asStringOrNull().orEmpty().trim(),
                    "cost" to FirestoreJson.toFirestore(l["cost"]),
                    "rating" to FirestoreJson.toFirestore(l["rating"]),
                    "comment" to FirestoreJson.toFirestore(l["comment"]),
                    "chunks_used" to FirestoreJson.toFirestore(l["chunks_used"]),
                    "user_corrections" to FirestoreJson.toFirestore(l["user_corrections"].takeUnless { it.isPyFalsy() } ?: JsonArray(emptyList())),
                    "created_at" to created,
                )
            }
    }
}
