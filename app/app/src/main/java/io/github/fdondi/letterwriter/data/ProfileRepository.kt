package io.github.fdondi.letterwriter.data

import com.google.firebase.Timestamp
import com.google.firebase.firestore.DocumentReference
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.SetOptions
import io.github.fdondi.letterwriter.core.ApiKeys
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.llm.ModelOverrides
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.tasks.await
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

class ProfileMissingException(sub: String) : IllegalStateException(
    "No profile personal_data/$sub exists. Sign in once on the desktop app with this Google account; " +
        "the phone never creates profiles.",
)

/** `personal_data/{sub}` and its API keys. [ProfileRepository] is the Firestore one; tests use an in-memory one. */
interface ProfileStore {
    /** The last profile loaded or written; screens read it. */
    val profile: StateFlow<UserProfile?>

    suspend fun load(sub: String): UserProfile

    fun current(): UserProfile = profile.value ?: throw IllegalStateException("Profile not loaded")

    suspend fun appendCvRevision(sub: String, content: String, source: String = "manual_edit")

    suspend fun saveDefaultVendors(sub: String, vendors: List<String>)

    suspend fun saveExtractionVendor(sub: String, vendor: String)

    suspend fun saveBackgroundModels(sub: String, models: List<String>, allowed: Set<String>)

    suspend fun saveRoleOverrides(sub: String, raw: JsonObject)

    suspend fun saveLanguages(sub: String, entries: List<LanguageEntry>)

    suspend fun saveTranslationProvider(sub: String, provider: String)

    suspend fun saveInstruction(sub: String, kind: InstructionKind, text: String)

    suspend fun clearInstruction(sub: String, kind: InstructionKind)

    suspend fun saveExtraInfo(sub: String, rows: List<JsonObject>)

    suspend fun mergeFeedbackExtraInfo(sub: String, feedbackRows: List<JsonObject>)

    suspend fun mergeFeedbackAgentContext(sub: String, feedbackRows: List<JsonObject>)

    suspend fun loadApiKeys(sub: String): ApiKeys

    suspend fun saveApiKey(sub: String, field: String, value: String)
}

/** Reads and writes `personal_data/{sub}` with the same field shapes as `api/personal_data.py`. */
class ProfileRepository(
    private val db: () -> FirebaseFirestore,
    private val instructionDefaults: InstructionDefaults,
    private val modelOverrides: ModelOverrides,
) : ProfileStore {
    private val _profile = MutableStateFlow<UserProfile?>(null)
    override val profile: StateFlow<UserProfile?> = _profile.asStateFlow()

    private fun doc(sub: String): DocumentReference = db().collection("personal_data").document(sub)

    override suspend fun load(sub: String): UserProfile {
        val snap = doc(sub).get().await()
        if (!snap.exists()) throw ProfileMissingException(sub)
        return UserProfile(sub, FirestoreJson.toJsonObject(snap.data)).also { _profile.value = it }
    }

    private suspend fun update(sub: String, updates: Map<String, Any?>) {
        doc(sub).set(updates + ("updated_at" to Timestamp.now()), SetOptions.merge()).await()
        load(sub)
    }

    private fun wrap(value: Any?): Map<String, Any?> = mapOf("value" to value, "updated_at" to Timestamp.now())

    /** Raw revisions are re-written as read so their Firestore Timestamps stay Timestamps. */
    override suspend fun appendCvRevision(sub: String, content: String, source: String) {
        val existing = (doc(sub).get().await().get("cv_revisions") as? List<*>).orEmpty()
        val newRevision = mapOf(
            "content" to content.trim(),
            "source" to source,
            "created_at" to Timestamp.now(),
            "revision_number" to (existing.size + 1).toLong(),
        )
        update(sub, mapOf("cv_revisions" to existing + newRevision))
    }

    override suspend fun saveDefaultVendors(sub: String, vendors: List<String>) = update(sub, mapOf("models" to wrap(vendors)))

    override suspend fun saveExtractionVendor(sub: String, vendor: String) {
        val v = vendor.trim().lowercase()
        require(v in ModelOverrides.VALID_VENDOR_KEYS) { "extraction_vendor must be one of ${ModelOverrides.VALID_VENDOR_KEYS.sorted()}" }
        update(sub, mapOf("extraction_vendor" to wrap(v)))
    }

    override suspend fun saveBackgroundModels(sub: String, models: List<String>, allowed: Set<String>) {
        update(sub, mapOf("background_models" to wrap(models.filter { it in allowed })))
    }

    override suspend fun saveRoleOverrides(sub: String, raw: JsonObject) {
        val cleaned = modelOverrides.normalize(raw)
        val wrapped = wrap(cleaned)
        update(sub, mapOf("vendor_role_model_overrides" to wrapped, "phase_model_overrides" to wrapped))
    }

    override suspend fun saveLanguages(sub: String, entries: List<LanguageEntry>) {
        update(sub, mapOf("default_languages" to entries.map { FirestoreJson.toFirestore(it.toJson()) }))
    }

    override suspend fun saveTranslationProvider(sub: String, provider: String) {
        val p = provider.trim().lowercase()
        require(p == "google" || p == "llm") { "translation_provider must be 'google' or 'llm'" }
        update(sub, mapOf("translation_provider" to wrap(p)))
    }

    /** Desktop `_save_custom_instruction`: stores the text plus the default it was based on. */
    override suspend fun saveInstruction(sub: String, kind: InstructionKind, text: String) {
        require(text.isNotBlank()) { "Instructions cannot be empty" }
        val (defaultText, defaultHash) = instructionDefaults.default(kind)
        val wrapped = wrap(text) + mapOf("default_baseline_hash" to defaultHash) +
            (if (defaultText.isNotEmpty()) mapOf("default_baseline_text" to defaultText) else emptyMap())
        update(sub, mapOf(kind.firestoreKeys.first() to wrapped))
    }

    override suspend fun clearInstruction(sub: String, kind: InstructionKind) {
        update(sub, kind.firestoreKeys.associateWith { FieldValue.delete() })
    }

    /** Desktop `_normalize_extra_info` + `_stamp_extra_info_items` for the CV tab's notes. */
    override suspend fun saveExtraInfo(sub: String, rows: List<JsonObject>) {
        val previous = load(sub).extraInfo.associateBy { it.textOrEmpty("id") }
        val now = Timestamp.now()
        val prevTimestamps = (doc(sub).get().await().get("extra_info") as? List<*>).orEmpty()
            .mapNotNull { it as? Map<*, *> }
            .associate { it["id"].toString() to it["updated_at"] }
        val out = rows.map { row ->
            val normalized = normalizeExtraInfoRow(row)
            val id = normalized["id"] as String
            val prev = previous[id]?.let { runCatching { normalizeExtraInfoRow(it) }.getOrNull() }
            normalized + ("updated_at" to (if (prev == normalized) prevTimestamps[id] ?: now else now))
        }
        update(sub, mapOf("extra_info" to out))
    }

    /** Desktop `_apply_feedback_extra_info_merge`: manual rows kept, feedback rows replaced. */
    override suspend fun mergeFeedbackExtraInfo(sub: String, feedbackRows: List<JsonObject>) {
        val now = Timestamp.now()
        val normalized = feedbackRows.map { normalizeExtraInfoRow(it) + ("updated_at" to now) }
        normalized.forEach { require(it["source"] == "feedback") { "each entry in feedback_extra_info must have source \"feedback\"" } }
        val raw = (doc(sub).get().await().get("extra_info") as? List<*>).orEmpty().mapNotNull { it as? Map<*, *> }
        val manual = raw.filter { (it["source"]?.toString()?.ifEmpty { null } ?: "manual").lowercase() != "feedback" }
        update(sub, mapOf("extra_info" to manual + normalized))
    }

    /** Desktop `_apply_feedback_agent_context_merge`. */
    override suspend fun mergeFeedbackAgentContext(sub: String, feedbackRows: List<JsonObject>) {
        val now = Timestamp.now()
        val normalized = feedbackRows.map { row ->
            val id = row.textOrEmpty("id").trim()
            require(id.isNotEmpty()) { "each agent_feedback_context item must have a non-empty id" }
            val src = row.textOrEmpty("source").trim().lowercase()
            require(src.isEmpty() || src == "feedback") { "agent_feedback_context.source must be \"feedback\" if set" }
            require(row.textOrEmpty("user_context").isNotBlank()) {
                "agent_feedback_context rows from feedback must include non-empty user_context"
            }
            mapOf(
                "id" to id,
                "source" to "feedback",
                "category" to row.textOrEmpty("category"),
                "user_context" to row.textOrEmpty("user_context"),
                "user_instructions" to row.textOrEmpty("user_instructions").trim(),
                "updated_at" to now,
            )
        }
        val raw = (doc(sub).get().await().get("agent_feedback_context") as? List<*>).orEmpty().mapNotNull { it as? Map<*, *> }
        val manual = raw.filter { (it["source"]?.toString()?.ifEmpty { null } ?: "feedback").lowercase() != "feedback" }
        update(sub, mapOf("agent_feedback_context" to manual + normalized))
    }

    override suspend fun loadApiKeys(sub: String): ApiKeys {
        val snap = doc(sub).collection("secrets").document("api_keys").get().await()
        val values = (snap.data ?: emptyMap()).mapNotNull { (k, v) -> (v as? String)?.let { k to it } }.toMap()
        return ApiKeys(values)
    }

    override suspend fun saveApiKey(sub: String, field: String, value: String) {
        require(field in ApiKeys.ALL) { "Unknown API key field $field" }
        val ref = doc(sub).collection("secrets").document("api_keys")
        val v = value.trim()
        ref.set(mapOf(field to if (v.isEmpty()) FieldValue.delete() else v), SetOptions.merge()).await()
    }

    companion object {
        fun normalizeExtraInfoRow(it: JsonObject): Map<String, Any?> {
            val id = it.textOrEmpty("id").trim()
            require(id.isNotEmpty()) { "each extra_info item must have a non-empty id" }
            val src = it.textOrEmpty("source").trim().lowercase()
            require(src.isEmpty() || src == "feedback" || src == "manual") { "extra_info.source must be 'feedback' or 'manual' if set" }
            require(src != "feedback" || it.textOrEmpty("user_context").isNotBlank()) {
                "extra_info rows from feedback must include non-empty user_context (CV Q&A)"
            }
            val lines = (it["context_lines"] as? JsonArray).orEmpty()
                .map { l -> l.asStringOrNull() ?: l.toString() }
            return mapOf(
                "id" to id,
                "source" to src.ifEmpty { "manual" },
                "category" to it.textOrEmpty("category"),
                "observation" to it.textOrEmpty("observation"),
                "user_context" to it.textOrEmpty("user_context"),
                "user_instructions" to it.textOrEmpty("user_instructions").trim(),
                "context_lines" to lines,
                "manual_text" to it.textOrEmpty("manual_text").trim(),
            )
        }
    }
}
