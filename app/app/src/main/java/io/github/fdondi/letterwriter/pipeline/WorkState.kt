package io.github.fdondi.letterwriter.pipeline

import android.content.Context
import androidx.datastore.core.CorruptionException
import androidx.datastore.core.DataStore
import androidx.datastore.core.DataStoreFactory
import androidx.datastore.core.Serializer
import androidx.datastore.core.handlers.ReplaceFileCorruptionHandler
import io.github.fdondi.letterwriter.core.Json
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.serialization.SerializationException
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.InputStream
import java.io.OutputStream
import java.time.Instant
import java.util.UUID

/** Where one vendor column is in the plan → draft → refine flow. */
@Serializable
enum class VendorStage { NOT_STARTED, PLAN, DRAFT, FINAL }

/** One vendor column. Feedback stays JSON so it can be saved to Firestore as is. */
@Serializable
data class VendorWork(
    val vendor: String,
    val stage: VendorStage = VendorStage.NOT_STARTED,
    val letterPlan: String = "",
    val draftLetter: String = "",
    /** The draft text as the user edited it before refine. */
    val draftEdited: String? = null,
    val knownWeaknesses: JsonArray = JsonArray(emptyList()),
    /** Category to item list, as returned by the draft phase. */
    val feedback: JsonObject = JsonObject(emptyMap()),
    /** Category to the user's edited item list; replaces [feedback] for that category. */
    val feedbackOverrides: JsonObject = JsonObject(emptyMap()),
    /** PLEASE_FIX item id to "the user approved it". */
    val itemApprovals: Map<String, Boolean> = emptyMap(),
    /** Categories whose check failed on every attempt, with the reason. */
    val checkErrors: Map<String, String> = emptyMap(),
    val finalLetter: String = "",
    /** Phase to dollars spent on this vendor. */
    val costs: Map<String, Double> = emptyMap(),
    val warnings: List<String> = emptyList(),
    val error: String? = null,
    /** The user's 1–5 rating of this vendor's letter, saved with the document. */
    val rating: Int? = null,
    val comment: String = "",
) {
    /** `mergeCategoryItems`: the user's override list when present, otherwise the original. */
    fun items(category: String): List<JsonObject> =
        FeedbackUi.normalizeCategoryItems(feedbackOverrides[category] ?: feedback[category], category)

    fun itemsByCategory(): LinkedHashMap<String, List<JsonObject>> =
        FeedbackItems.CATEGORIES.associateWithTo(LinkedHashMap()) { items(it) }

    fun mergedFeedback(): JsonObject = JsonObject(feedback + feedbackOverrides)

    /** The draft can go to refine once every visible PLEASE_FIX comment is approved. */
    fun allApproved(): Boolean = FeedbackItems.CATEGORIES.all { FeedbackUi.categoryAllItemsApproved(items(it), itemApprovals) }

    val totalCost: Double get() = costs.values.sum()
}

/** One paragraph of the assembled letter and the vendor letter it came from. */
@Serializable
data class FinalParagraph(
    val id: String = UUID.randomUUID().toString(),
    val vendor: String,
    val originalText: String,
    val text: String,
)

/** The job being written for, everything the intake screen gathers. */
@Serializable
data class JobIntake(
    val jobText: String = "",
    val companyName: String = "",
    val jobTitle: String = "",
    val location: String = "",
    val language: String = "",
    val salary: String = "",
    val sourceUrl: String = "",
    val pointOfContact: JsonObject? = null,
    val hireProblem: String = "",
    val requirements: List<String> = emptyList(),
    /** Skill to `{need, level}`. */
    val competences: JsonObject = JsonObject(emptyMap()),
    val additionalUserInfo: String = "",
    val additionalCompanyInfo: String = "",
    val extracted: Boolean = false,
    /** Sanitized similar letters with their rerank scores. */
    val similarDocuments: List<JsonObject> = emptyList(),
    /** Ids of [similarDocuments] used as examples (defaults to the rerank's top 3). */
    val selectedDocIds: List<String> = emptyList(),
    val decisionDetail: String = "",
    /** Model id to `{report, updated_at}` or `{error}`. */
    val companyReports: JsonObject = JsonObject(emptyMap()),
    val researchSource: String = "",
    val selectedReportModel: String? = null,
    /** The report text used by every vendor (the picked report, possibly edited). */
    val companyReport: String = "",
    val pocReports: JsonObject = JsonObject(emptyMap()),
    val warnings: List<String> = emptyList(),
    val costs: Map<String, Double> = emptyMap(),
)

@Serializable
data class WorkSession(
    val sessionId: String = UUID.randomUUID().toString(),
    val createdAt: String = Instant.now().toString(),
    val intake: JobIntake = JobIntake(),
    val vendors: List<String> = emptyList(),
    val includePlanStep: Boolean = true,
    val work: Map<String, VendorWork> = emptyMap(),
    /** Set once the letter is saved to Previous Examples, so later saves update it. */
    val documentId: String? = null,
    /** Paragraphs picked from the vendor letters; the saved letter is their texts joined by blank lines. */
    val paragraphs: List<FinalParagraph> = emptyList(),
    /** Answers typed for an input cluster, offered to the same cluster in other vendors (`inputClusterText`). */
    val inputClusterText: Map<String, String> = emptyMap(),
) {
    fun vendorWork(vendor: String): VendorWork = work[vendor] ?: VendorWork(vendor)

    val finalText: String get() = paragraphs.joinToString("\n\n") { it.text.trim() }.trim()

    /** `effectiveTopDocs`: the picked similar letters in rerank order; letters the ranker did not score get 5. */
    fun selectedTopDocs(): List<JsonObject> {
        val ids = intake.selectedDocIds.toSet()
        return intake.similarDocuments.filter { docKey(it) in ids }.map { d ->
            if ("score" in d) d else JsonObject(d + ("score" to JsonPrimitive(5)))
        }
    }

    companion object {
        /** `d.id || d.company_name`. */
        fun docKey(doc: JsonObject): String =
            (doc["id"] as? JsonPrimitive)?.content?.takeIf { it.isNotEmpty() }
                ?: (doc["company_name"] as? JsonPrimitive)?.content.orEmpty()
    }
}

private object WorkSessionSerializer : Serializer<WorkSession?> {
    override val defaultValue: WorkSession? = null

    override suspend fun readFrom(input: InputStream): WorkSession? {
        val text = input.readBytes().decodeToString()
        if (text.isBlank() || text == "null") return null
        return try {
            Json.codec.decodeFromString(WorkSession.serializer(), text)
        } catch (e: SerializationException) {
            throw CorruptionException("Saved work session is unreadable", e)
        } catch (e: IllegalArgumentException) {
            throw CorruptionException("Saved work session is unreadable", e)
        }
    }

    override suspend fun writeTo(t: WorkSession?, output: OutputStream) {
        val text = if (t == null) "null" else Json.codec.encodeToString(WorkSession.serializer(), t)
        output.write(text.encodeToByteArray())
    }
}

/**
 * The in-progress letter survives app restarts (DataStore file `work_session.json`).
 * An unreadable file is cleared so the app can start, and [corruption] keeps the reason for the UI.
 */
class WorkSessionStore(context: Context) {
    private val _corruption = MutableStateFlow<String?>(null)
    val corruption: StateFlow<String?> = _corruption.asStateFlow()

    private val store: DataStore<WorkSession?> = DataStoreFactory.create(
        serializer = WorkSessionSerializer,
        corruptionHandler = ReplaceFileCorruptionHandler { e ->
            _corruption.value = "The saved letter in progress could not be read and was discarded: ${e.cause?.message ?: e.message}"
            null
        },
        produceFile = { context.filesDir.resolve("datastore/work_session.json") },
    )

    fun dismissCorruption() {
        _corruption.value = null
    }

    val session: Flow<WorkSession?> = store.data

    suspend fun current(): WorkSession? = store.data.first()

    suspend fun update(transform: (WorkSession?) -> WorkSession?): WorkSession? = store.updateData { transform(it) }
}
