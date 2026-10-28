package io.github.fdondi.letterwriter.demo

import android.app.Activity
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.Backend
import io.github.fdondi.letterwriter.auth.AuthGateway
import io.github.fdondi.letterwriter.auth.BigQueryAuth
import io.github.fdondi.letterwriter.auth.SignedInUser
import io.github.fdondi.letterwriter.core.ApiKeys
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.cost.BigQueryApi
import io.github.fdondi.letterwriter.cost.QueryParam
import io.github.fdondi.letterwriter.data.CompanyStore
import io.github.fdondi.letterwriter.data.CompanyWriteResult
import io.github.fdondi.letterwriter.data.DocumentStore
import io.github.fdondi.letterwriter.data.EmbeddingService
import io.github.fdondi.letterwriter.data.FirestoreJson
import io.github.fdondi.letterwriter.data.InMemoryOpportunityStore
import io.github.fdondi.letterwriter.data.InstructionDefaults
import io.github.fdondi.letterwriter.data.InstructionKind
import io.github.fdondi.letterwriter.data.LanguageEntry
import io.github.fdondi.letterwriter.data.Opportunity
import io.github.fdondi.letterwriter.data.ProfileStore
import io.github.fdondi.letterwriter.data.SimilarDocument
import io.github.fdondi.letterwriter.data.StoredDocument
import io.github.fdondi.letterwriter.data.UserProfile
import io.github.fdondi.letterwriter.llm.ModelOverrides
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.time.Instant
import java.util.UUID
import kotlin.math.sqrt

/** The demo account's data: everything in memory, seeded from [fixtures] (`assets/fixtures`). */
object DemoData {
    const val JOBS_FIXTURE = "demo_opportunities.json"

    private val DEMO_CV = """
        [DEMO] Demo Applicant — software engineer
        - 8 years of C++ and CUDA on embedded and GPU systems
        - Python tooling, CI, code review; some Rust
        - German B2, English C1
    """.trimIndent()

    fun backend(graph: AppGraph, onLeave: () -> Unit): Backend {
        val (jobs, sessions) = jobs { graph.debugFixtures.text(it) }
        return Backend(
            auth = DemoAuth(onLeave),
            profiles = DemoProfiles(graph.instructionDefaults, graph.modelOverrides),
            documents = DemoDocuments(seedDocuments()),
            companies = DemoCompanies(),
            opportunities = InMemoryOpportunityStore(jobs, sessions),
            embeddings = HashEmbeddings(),
            bigQuery = NoBigQuery(),
        )
    }

    /** The UI harness jobs (one per Jobs tab; the ready one has desktop drafts), owned by the demo user. */
    fun jobs(read: (String) -> String): Pair<List<Opportunity>, Map<String, JsonObject>> {
        val root = Json.parse(read(JOBS_FIXTURE)).jsonObject
        val jobs = (root["opportunities"] as? JsonArray).orEmpty().mapNotNull { it.asObjectOrNull() }.map { o ->
            Opportunity(o["id"].asStringOrNull().orEmpty(), JsonObject(o + ("user_id" to JsonPrimitive(DemoMode.USER.sub))))
        }
        val sessions = root["states"].asObjectOrNull().orEmpty().mapNotNull { (id, s) -> s.asObjectOrNull()?.let { id to it } }.toMap()
        return jobs to sessions
    }

    fun profileJson(): JsonObject = buildJsonObject {
        put("cv_revisions", JsonArray(listOf(buildJsonObject {
            put("content", DEMO_CV)
            put("source", "demo")
            put("created_at", "2026-01-01T00:00:00Z")
            put("revision_number", 1)
        })))
        put("models", wrap(JsonArray(listOf(JsonPrimitive("openai"), JsonPrimitive("anthropic")))))
        put("extraction_vendor", wrap(JsonPrimitive("openai")))
        put("translation_provider", wrap(JsonPrimitive("llm")))
    }

    fun seedDocuments(): List<StoredDocument> = listOf(
        demoDocument("demo-doc-1", "Example Robotics AG", "Senior C++ Engineer", "2026-03-02T09:00:00Z"),
        demoDocument("demo-doc-2", "Example Imaging SA", "GPU Software Engineer", "2026-05-14T09:00:00Z"),
    )

    private fun demoDocument(id: String, company: String, title: String, created: String) = StoredDocument(
        id,
        buildJsonObject {
            put("id", id)
            put("user_id", DemoMode.USER.sub)
            put("company_name", company)
            put("job_title", title)
            put("job_text", "[DEMO] $title at $company. C++, CUDA, embedded Linux.")
            put("letter_text", "[DEMO] Dear $company team,\n\nThis is a made-up example letter for demo mode.\n\nKind regards,\nDemo Applicant")
            put("created_at", created)
        },
    )

    fun wrap(value: JsonElement): JsonObject = buildJsonObject {
        put("value", value)
        put("updated_at", Instant.now().toString())
    }
}

class DemoAuth(private val onLeave: () -> Unit) : AuthGateway {
    private val _user = MutableStateFlow<SignedInUser?>(DemoMode.USER)
    override val user: StateFlow<SignedInUser?> = _user.asStateFlow()
    override val configurationProblem: String? = null

    override suspend fun signIn(activity: Activity): SignedInUser = DemoMode.USER.also { _user.value = it }

    /** Signing out of the demo account leaves demo mode. */
    override fun signOut() = onLeave()

    override suspend fun bigQueryAuth(): BigQueryAuth = BigQueryAuth.Token("demo")
}

class DemoProfiles(
    private val instructionDefaults: InstructionDefaults,
    private val modelOverrides: ModelOverrides,
    initial: JsonObject = DemoData.profileJson(),
) : ProfileStore {
    private var data = initial
    private val keys = HashMap<String, String>()
    private val _profile = MutableStateFlow<UserProfile?>(null)
    override val profile: StateFlow<UserProfile?> = _profile.asStateFlow()

    override suspend fun load(sub: String): UserProfile = UserProfile(sub, data).also { _profile.value = it }

    private suspend fun put(vararg fields: Pair<String, JsonElement>) {
        data = JsonObject(data + fields)
        _profile.value?.let { load(it.sub) }
    }

    private suspend fun remove(names: Collection<String>) {
        data = JsonObject(data - names.toSet())
        _profile.value?.let { load(it.sub) }
    }

    private fun list(key: String): List<JsonObject> = (data[key] as? JsonArray).orEmpty().mapNotNull { it.asObjectOrNull() }

    private fun stamped(row: JsonObject): JsonObject = JsonObject(row + ("updated_at" to JsonPrimitive(Instant.now().toString())))

    override suspend fun appendCvRevision(sub: String, content: String, source: String) {
        val revisions = list("cv_revisions")
        val revision = buildJsonObject {
            put("content", content.trim())
            put("source", source)
            put("created_at", Instant.now().toString())
            put("revision_number", revisions.size + 1)
        }
        put("cv_revisions" to JsonArray(revisions + revision))
    }

    override suspend fun saveDefaultVendors(sub: String, vendors: List<String>) =
        put("models" to DemoData.wrap(JsonArray(vendors.map(::JsonPrimitive))))

    override suspend fun saveExtractionVendor(sub: String, vendor: String) =
        put("extraction_vendor" to DemoData.wrap(JsonPrimitive(vendor.trim().lowercase())))

    override suspend fun saveBackgroundModels(sub: String, models: List<String>, allowed: Set<String>) =
        put("background_models" to DemoData.wrap(JsonArray(models.filter { it in allowed }.map(::JsonPrimitive))))

    override suspend fun saveRoleOverrides(sub: String, raw: JsonObject) {
        val wrapped = DemoData.wrap(FirestoreJson.toJson(modelOverrides.normalize(raw)))
        put("vendor_role_model_overrides" to wrapped, "phase_model_overrides" to wrapped)
    }

    override suspend fun saveLanguages(sub: String, entries: List<LanguageEntry>) =
        put("default_languages" to JsonArray(entries.map { it.toJson() }))

    override suspend fun saveTranslationProvider(sub: String, provider: String) =
        put("translation_provider" to DemoData.wrap(JsonPrimitive(provider.trim().lowercase())))

    override suspend fun saveInstruction(sub: String, kind: InstructionKind, text: String) {
        require(text.isNotBlank()) { "Instructions cannot be empty" }
        val (defaultText, defaultHash) = instructionDefaults.default(kind)
        val wrapped = JsonObject(
            DemoData.wrap(JsonPrimitive(text)) + mapOf(
                "default_baseline_hash" to JsonPrimitive(defaultHash),
                "default_baseline_text" to JsonPrimitive(defaultText),
            ),
        )
        put(kind.firestoreKeys.first() to wrapped)
    }

    override suspend fun clearInstruction(sub: String, kind: InstructionKind) = remove(kind.firestoreKeys)

    override suspend fun saveExtraInfo(sub: String, rows: List<JsonObject>) =
        put("extra_info" to JsonArray(rows.map(::stamped)))

    override suspend fun mergeFeedbackExtraInfo(sub: String, feedbackRows: List<JsonObject>) {
        val manual = list("extra_info").filter { (it["source"].asStringOrNull() ?: "manual").lowercase() != "feedback" }
        put("extra_info" to JsonArray(manual + feedbackRows.map(::stamped)))
    }

    override suspend fun mergeFeedbackAgentContext(sub: String, feedbackRows: List<JsonObject>) {
        val manual = list("agent_feedback_context").filter { (it["source"].asStringOrNull() ?: "feedback").lowercase() != "feedback" }
        put("agent_feedback_context" to JsonArray(manual + feedbackRows.map(::stamped)))
    }

    /**
     * Placeholders for every key, so every vendor can be picked. Nothing uses them: in demo mode
     * model calls are fixtures, and embeddings, translation and the decision model are skipped.
     */
    override suspend fun loadApiKeys(sub: String): ApiKeys =
        ApiKeys(ApiKeys.ALL.associateWith { DEMO_KEY } + keys)

    companion object {
        const val DEMO_KEY = "demo-placeholder-not-a-key"
    }

    override suspend fun saveApiKey(sub: String, field: String, value: String) {
        require(field in ApiKeys.ALL) { "Unknown API key field $field" }
        if (value.isBlank()) keys.remove(field) else keys[field] = value.trim()
    }
}

class DemoDocuments(seed: List<StoredDocument>) : DocumentStore {
    private val docs = LinkedHashMap(seed.associateBy { it.id })
    private var feedbackCount = 0

    override suspend fun list(sub: String, limit: Long): List<StoredDocument> =
        docs.values.filter { it.text("user_id") == sub }.sortedByDescending { it.text("created_at") }.take(limit.toInt())

    override suspend fun get(sub: String, id: String): StoredDocument? = docs[id]?.takeIf { it.text("user_id") == sub }

    override suspend fun delete(sub: String, id: String) {
        if (get(sub, id) != null) docs.remove(id)
    }

    override suspend fun upsert(sub: String, data: JsonObject): StoredDocument {
        val id = data["id"].asStringOrNull()?.takeIf { it.isNotBlank() } ?: "demo-${UUID.randomUUID()}"
        val previous = docs[id]?.data.orEmpty()
        val now = JsonPrimitive(Instant.now().toString())
        val merged = JsonObject(
            previous + data + mapOf(
                "id" to JsonPrimitive(id),
                "user_id" to JsonPrimitive(sub),
                "created_at" to (previous["created_at"] ?: now),
                "updated_at" to now,
            ),
        )
        return StoredDocument(id, merged).also { docs[id] = it }
    }

    override suspend fun saveFeedback(sub: String, documentId: String, letterText: String, aiLetters: JsonArray): Int {
        feedbackCount += aiLetters.size
        return aiLetters.size
    }

    override suspend fun savePhaseDraftFeedbackSnapshot(
        sub: String,
        sessionId: String,
        documentId: String?,
        vendor: String,
        feedback: JsonObject,
        feedbackOverrides: JsonObject?,
    ): String = "demo-snapshot-$sessionId-$vendor"

    /** Demo mode does not search: there are no embeddings to compare. */
    override suspend fun similar(sub: String, jobText: String, limit: Int): List<SimilarDocument> = emptyList()
}

class DemoCompanies : CompanyStore {
    private val companies = HashMap<String, JsonObject>()
    private val pocs = HashMap<String, JsonObject>()

    private fun key(name: String) = name.trim().lowercase()

    override suspend fun get(companyName: String): JsonObject? = companies[key(companyName)]

    override suspend fun save(companyName: String, data: JsonObject): CompanyWriteResult {
        val id = key(companyName)
        companies[id] = JsonObject(companies[id].orEmpty() + data + ("company_name" to JsonPrimitive(companyName)))
        return CompanyWriteResult(id, null)
    }

    override suspend fun saveAlias(aliasCompanyName: String, canonicalDocId: String, canonicalCompanyName: String?): CompanyWriteResult =
        CompanyWriteResult(key(aliasCompanyName), null)

    override suspend fun getPoc(companyName: String, pocName: String): JsonObject? = pocs["${key(companyName)}/${key(pocName)}"]

    override suspend fun savePoc(companyName: String, pocName: String, reports: JsonObject): String {
        val id = "${key(companyName)}/${key(pocName)}"
        pocs[id] = reports
        return id
    }

    override suspend fun searchSimilar(companyName: String, limit: Int): List<JsonObject> = emptyList()
}

/** Deterministic bag-of-words vectors, so anything that compares texts still works offline. */
class HashEmbeddings(private val dims: Int = 64) : EmbeddingService {
    override suspend fun embedBatch(texts: List<String>): List<DoubleArray> = texts.map { text ->
        val v = DoubleArray(dims)
        text.lowercase().split(Regex("\\W+")).filter { it.isNotEmpty() }.forEach { w -> v[Math.floorMod(w.hashCode(), dims)] += 1.0 }
        val norm = sqrt(v.sumOf { it * it }).takeIf { it > 0 } ?: 1.0
        DoubleArray(dims) { v[it] / norm }
    }
}

/** Costs are recorded locally only; nothing is sent. */
class NoBigQuery : BigQueryApi {
    override suspend fun insertAll(token: String, table: String, rows: List<Pair<String, JsonObject>>): Map<Int, String> = emptyMap()

    override suspend fun query(token: String, sql: String, params: List<QueryParam>): List<Map<String, String?>> = emptyList()

    override fun tableRef(table: String): String = "demo.$table"
}
