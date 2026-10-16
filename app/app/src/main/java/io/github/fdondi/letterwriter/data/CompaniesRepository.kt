package io.github.fdondi.letterwriter.data

import com.google.firebase.Timestamp
import com.google.firebase.firestore.CollectionReference
import com.google.firebase.firestore.FieldPath
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.SetOptions
import io.github.fdondi.letterwriter.core.asObjectOrNull
import kotlinx.coroutines.tasks.await
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Outcome of a write; [warning] is set when the name vector could not be stored (the desktop only logs this). */
data class CompanyWriteResult(val id: String, val warning: String?)

/** Port of the shared `companies` research cache functions in `firestore_store.py`. */
class CompaniesRepository(
    private val db: () -> FirebaseFirestore,
    private val embeddings: Embeddings,
) {
    private fun companies(): CollectionReference = db().collection("companies")

    suspend fun resolveDocId(docId: String, maxHops: Int = 3): String {
        var current = docId
        repeat(maxHops) {
            val snap = companies().document(current).get().await()
            if (!snap.exists()) return current
            val aliasFor = snap.get("alias_for")?.toString()
            if (aliasFor.isNullOrEmpty() || aliasFor == current) return current
            current = aliasFor
        }
        return current
    }

    /** `get_company_info`, with alias resolution. */
    suspend fun get(companyName: String): JsonObject? {
        require(companyName.isNotEmpty()) { "company_name is required" }
        val requested = normalizeDocId(companyName)
        val id = resolveDocId(requested)
        val snap = companies().document(id).get().await()
        if (!snap.exists()) return null
        val out = FirestoreJson.toJsonObject(snap.data).filterKeys { it != "vector" }.toMutableMap()
        if (requested != id) {
            out["resolved_from_alias"] = JsonPrimitive(requested)
            out["resolved_to"] = JsonPrimitive(id)
        }
        return JsonObject(out)
    }

    /** `save_company_info`: merges, never persists `reports.*.top_docs`. */
    suspend fun save(companyName: String, data: JsonObject): CompanyWriteResult {
        require(companyName.isNotEmpty()) { "company_name is required" }
        val id = normalizeDocId(companyName)
        val ref = companies().document(id)
        val reports = data["reports"]
        val update = mutableMapOf<String, Any?>("id" to id, "company_name" to companyName, "updated_at" to Timestamp.now())
        data.filterKeys { it != "reports" }.forEach { (k, v) -> update[k] = FirestoreJson.toFirestore(v) }
        if (reports != null) update["reports"] = FirestoreJson.toFirestore(stripTopDocs(reports))
        val warning = runCatching { embeddings.embed(companyName) }
            .onSuccess { update["vector"] = FieldValue.vector(it) }
            .exceptionOrNull()?.let { "Company name vector not stored (similar-company lookup will miss it): ${it.message}" }
        ref.set(update, SetOptions.merge()).await()

        val modelKeys = (reports as? JsonObject)?.filterValues { it is JsonObject }?.keys.orEmpty().toList()
        if (modelKeys.isNotEmpty()) {
            val first = FieldPath.of("reports", modelKeys[0], "top_docs")
            val rest = modelKeys.drop(1).flatMap { listOf(FieldPath.of("reports", it, "top_docs"), FieldValue.delete()) }
            ref.update(first, FieldValue.delete(), *rest.toTypedArray()).await()
        }
        return CompanyWriteResult(id, warning)
    }

    /** `save_company_alias`. */
    suspend fun saveAlias(aliasCompanyName: String, canonicalDocId: String, canonicalCompanyName: String?): CompanyWriteResult {
        require(aliasCompanyName.isNotEmpty() && canonicalDocId.isNotEmpty()) { "alias_company_name and canonical_doc_id are required" }
        val aliasId = normalizeDocId(aliasCompanyName)
        val root = resolveDocId(canonicalDocId)
        if (aliasId == root) return CompanyWriteResult(aliasId, null)
        val payload = mutableMapOf<String, Any?>(
            "id" to aliasId,
            "company_name" to aliasCompanyName,
            "alias_for" to root,
            "canonical_company_name" to canonicalCompanyName.orEmpty(),
            "updated_at" to Timestamp.now(),
        )
        val warning = runCatching { embeddings.embed(aliasCompanyName) }
            .onSuccess { payload["vector"] = FieldValue.vector(it) }
            .exceptionOrNull()?.let { "Alias vector not stored: ${it.message}" }
        companies().document(aliasId).set(payload, SetOptions.merge()).await()
        return CompanyWriteResult(aliasId, warning)
    }

    /** `get_poc_info`: the `pocs.<key>` entry of the (alias-resolved) company doc. */
    suspend fun getPoc(companyName: String, pocName: String): JsonObject? {
        require(companyName.isNotEmpty() && pocName.isNotEmpty()) { "company_name and poc_name are required" }
        val id = resolveDocId(normalizeDocId(companyName))
        val snap = companies().document(id).get().await()
        if (!snap.exists()) return null
        return FirestoreJson.toJsonObject(snap.data)["pocs"].asObjectOrNull()?.get(normalizePocKey(pocName)).asObjectOrNull()
    }

    /**
     * `save_poc_info`. The desktop writes to the unresolved company id while reading
     * through aliases; the phone writes to the resolved id so the next read finds it.
     */
    suspend fun savePoc(companyName: String, pocName: String, reports: JsonObject): String {
        require(companyName.isNotEmpty() && pocName.isNotEmpty()) { "company_name and poc_name are required" }
        val id = resolveDocId(normalizeDocId(companyName))
        val now = Timestamp.now()
        val update = mapOf(
            "pocs" to mapOf(
                normalizePocKey(pocName) to mapOf(
                    "name" to pocName,
                    "updated_at" to now,
                    "reports" to FirestoreJson.toFirestore(reports),
                ),
            ),
            "company_name" to companyName,
            "updated_at" to now,
        )
        companies().document(id).set(update, SetOptions.merge()).await()
        return id
    }

    /**
     * `search_similar_companies`. The Android SDK has no `find_nearest`, so the
     * shared collection is scored on the device (over-fetch max(limit*3, 10), then
     * flatten aliases to canonical docs and dedupe).
     */
    suspend fun searchSimilar(companyName: String, limit: Int = 5): List<JsonObject> {
        if (companyName.isEmpty()) return emptyList()
        val query = embeddings.embed(companyName)
        val snaps = companies().get().await().documents
        val candidates = snaps.mapNotNull { s ->
            val vec = Embeddings.vectorOf(s.get("vector")) ?: return@mapNotNull null
            val sim = Embeddings.cosine(query, vec)
            if (sim.isNaN()) null else Triple(s.id, s.data, sim)
        }.sortedByDescending { it.third }.take(maxOf(limit * 3, 10))

        val out = mutableListOf<JsonObject>()
        val seen = mutableSetOf<String>()
        for ((candidateId, data, _) in candidates) {
            val canonicalId = resolveDocId(candidateId)
            if (canonicalId in seen) continue
            if (canonicalId != candidateId) {
                val snap = companies().document(canonicalId).get().await()
                if (!snap.exists()) continue
                val canonical = FirestoreJson.toJsonObject(snap.data).filterKeys { it != "vector" }.toMutableMap()
                canonical["id"] = JsonPrimitive(canonicalId)
                canonical["matched_via_alias"] = JsonPrimitive(candidateId)
                canonical["matched_alias_name"] = JsonPrimitive(data?.get("company_name")?.toString())
                out += JsonObject(canonical)
            } else {
                val c = FirestoreJson.toJsonObject(data).filterKeys { it != "vector" }.toMutableMap()
                c["id"] = JsonPrimitive(candidateId)
                out += JsonObject(c)
            }
            seen += canonicalId
            if (out.size >= limit) break
        }
        return out
    }

    companion object {
        fun normalizeDocId(companyName: String): String = companyName.trim().lowercase().replace(" ", "_")

        fun normalizePocKey(pocName: String): String = pocName.trim().lowercase().replace(" ", "_")

        fun stripTopDocs(reports: JsonElement): JsonElement {
            val obj = reports.asObjectOrNull() ?: return reports
            return JsonObject(obj.mapValues { (_, entry) -> (entry as? JsonObject)?.let { e -> JsonObject(e.filterKeys { it != "top_docs" }) } ?: entry })
        }
    }
}
