package io.github.fdondi.letterwriter.data

import com.google.firebase.Timestamp
import com.google.firebase.firestore.CollectionReference
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.SetOptions
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.tasks.await
import kotlinx.serialization.json.JsonObject

/** A job posting the phone hands to the desktop pipeline. */
data class CaptureRequest(
    /** The posting text; empty when only a link was shared (the job then waits for its text). */
    val text: String,
    val url: String,
    /** `capture.via`: `share_text` for pasted or shared text, `share_url` for text fetched from the link. */
    val via: String,
    /** `vendors_requested`; empty means every vendor (the desktop has no defaults of its own). */
    val vendorsRequested: List<String> = emptyList(),
    /** `rewrite_rounds`: comments → rewrite rounds on the desktop (0–2); null leaves the batch's default (1). */
    val rewriteRounds: Int? = null,
    /** `final_feedback`: comment the last version for the paragraph review; null leaves the batch's default (on). */
    val finalFeedback: Boolean? = null,
)

data class CaptureOutcome(val id: String, val status: OpportunityStatus, val message: String)

/**
 * The `opportunities` collection shared with the desktop pipeline (OPPORTUNITY_PIPELINE_PLAN.md §3).
 * The phone captures postings and moves jobs between the states it owns; only the desktop
 * writes drafts (`state/session`). Tests use an in-memory one.
 */
interface OpportunityStore {
    /** The user's opportunities, most recently changed first. Emits again whenever one changes. */
    fun observe(sub: String): Flow<List<Opportunity>>

    suspend fun get(sub: String, id: String): Opportunity?

    /** Creates the job or attaches the posting to the one with the same link ([OpportunityRules.planCapture]). */
    suspend fun capture(sub: String, request: CaptureRequest): CaptureOutcome

    /** Attaches posting [text] to job [id] and queues it for drafting ([OpportunityRules.planUpdate]). */
    suspend fun attachCapture(sub: String, id: String, text: String, via: String): CaptureOutcome

    /**
     * Moves a job from one of [from] to [to] and writes [fields] (plain values) with it.
     * Throws when the job has meanwhile moved to another state.
     */
    suspend fun transition(
        sub: String,
        id: String,
        from: Set<OpportunityStatus>,
        to: OpportunityStatus,
        fields: Map<String, Any?> = emptyMap(),
    ): Opportunity

    /** `opportunities/{id}/state/session`: the desktop session with the drafts, or null before the batch wrote it. */
    suspend fun loadSession(sub: String, id: String): JsonObject?
}

/** One write of [OpportunityRules.planCapture]; [fields] null means nothing changes. */
data class CapturePlan(val id: String, val fields: Map<String, Any?>?, val merge: Boolean, val outcome: CaptureOutcome)

/** State rules both stores share, so the in-memory one behaves like Firestore. */
object OpportunityRules {
    /** States the phone may set; `drafting`, `ready` and `failed` belong to the desktop batch. */
    val PHONE_STATES = setOf(
        OpportunityStatus.PROPOSED,
        OpportunityStatus.APPROVED,
        OpportunityStatus.SKIPPED,
        OpportunityStatus.CAPTURED,
        OpportunityStatus.DONE,
        OpportunityStatus.APPLIED,
    )

    /** States in which a new posting text replaces the job's capture and queues it for drafting. */
    private val RECAPTURABLE = setOf(
        OpportunityStatus.PROPOSED,
        OpportunityStatus.APPROVED,
        OpportunityStatus.SKIPPED,
        OpportunityStatus.CAPTURED,
        OpportunityStatus.FAILED,
        OpportunityStatus.UNKNOWN,
    )

    fun canonicalKeyFor(request: CaptureRequest): String {
        val url = request.url.trim()
        val text = request.text.trim()
        require(url.isNotEmpty() || text.isNotEmpty()) { "Paste the job text or a link first." }
        return if (url.isNotEmpty()) OpportunityKeys.canonicalKey(url) else OpportunityKeys.textKey(text)
    }

    fun idFor(sub: String, request: CaptureRequest): String = OpportunityKeys.documentId(sub, canonicalKeyFor(request))

    /**
     * New job: `captured` with the text, or `approved` (waiting for its text) when only a link came.
     * Existing job: text attaches and queues it again unless the desktop is drafting it or already did;
     * a bare link only approves a proposed or skipped job.
     */
    fun planCapture(sub: String, request: CaptureRequest, existing: Opportunity?, now: Timestamp): CapturePlan {
        val key = canonicalKeyFor(request)
        val id = OpportunityKeys.documentId(sub, key)
        val text = request.text.trim()
        val url = request.url.trim()
        val capture = if (text.isEmpty()) null else mapOf("text" to text, "html" to null, "captured_at" to now, "via" to request.via)
        val vendors = request.vendorsRequested.distinct()

        if (existing == null) {
            val status = if (capture != null) OpportunityStatus.CAPTURED else OpportunityStatus.APPROVED
            val fields = linkedMapOf<String, Any?>(
                "user_id" to sub,
                "canonical_key" to key,
                "source" to OpportunityKeys.sourceOf(key),
                "url" to if (url.isEmpty()) "" else OpportunityKeys.cleanUrl(url),
                "title" to "",
                "company" to "",
                "location" to "",
                "status" to status.key,
                "skip_reason" to null,
                "alert_message_ids" to emptyList<String>(),
                "capture" to capture,
                "created_at" to now,
                "updated_at" to now,
            )
            if (vendors.isNotEmpty()) fields["vendors_requested"] = vendors
            fields.putAll(draftSettings(request))
            val message = if (capture != null) {
                "Saved. The desktop drafts it on its next run."
            } else {
                "Link saved. Add the posting text under Job pipeline → Needs text."
            }
            return CapturePlan(id, fields, merge = false, CaptureOutcome(id, status, message))
        }

        return planUpdate(sub, existing, capture, url, vendors, now, draftSettings(request))
    }

    /** `rewrite_rounds` / `final_feedback` the request sets (rounds clamped to 0–2). */
    private fun draftSettings(request: CaptureRequest): Map<String, Any?> = buildMap {
        request.rewriteRounds?.let { put("rewrite_rounds", it.coerceIn(0, 2).toLong()) }
        request.finalFeedback?.let { put("final_feedback", it) }
    }

    /**
     * An existing job gets new posting text ([capture]) or, with none, a bare link. Text attaches and
     * queues the job again unless the desktop is drafting it or already did; a bare link only
     * approves a proposed or skipped job.
     */
    fun planUpdate(
        sub: String,
        existing: Opportunity,
        capture: Map<String, Any?>?,
        url: String,
        vendors: List<String>,
        now: Timestamp,
        settings: Map<String, Any?> = emptyMap(),
    ): CapturePlan {
        val id = existing.id
        if (existing.userId != sub) throw SecurityException("Opportunity $id belongs to a different user")
        val current = existing.status
        fun unchanged(message: String) = CapturePlan(id, null, merge = true, CaptureOutcome(id, current, message))
        when (current) {
            OpportunityStatus.DRAFTING -> return unchanged("The desktop is drafting this job right now.")
            OpportunityStatus.READY -> return unchanged("Drafts for this job are already ready under Job pipeline → Ready.")
            OpportunityStatus.DONE, OpportunityStatus.APPLIED -> return unchanged("This job is already done.")
            else -> Unit
        }
        if (capture == null) {
            if (current != OpportunityStatus.PROPOSED && current != OpportunityStatus.SKIPPED) {
                return unchanged("This job is already in the pipeline.")
            }
            val fields = mapOf("status" to OpportunityStatus.APPROVED.key, "skip_reason" to null, "updated_at" to now)
            return CapturePlan(id, fields, merge = true, CaptureOutcome(id, OpportunityStatus.APPROVED, "Approved. Add the posting text under Job pipeline → Needs text."))
        }
        check(current in RECAPTURABLE)
        val fields = linkedMapOf<String, Any?>(
            "status" to OpportunityStatus.CAPTURED.key,
            "capture" to capture,
            "skip_reason" to null,
            "updated_at" to now,
        )
        if (vendors.isNotEmpty()) fields["vendors_requested"] = vendors
        fields.putAll(settings)
        if (existing.url.isEmpty() && url.isNotEmpty()) fields["url"] = OpportunityKeys.cleanUrl(url)
        val message = if (current == OpportunityStatus.CAPTURED) {
            "Posting text replaced. The desktop drafts it on its next run."
        } else {
            "Posting text attached. The desktop drafts it on its next run."
        }
        return CapturePlan(id, fields, merge = true, CaptureOutcome(id, OpportunityStatus.CAPTURED, message))
    }

    fun planAttach(sub: String, existing: Opportunity?, id: String, text: String, via: String, now: Timestamp): CapturePlan {
        if (existing == null) throw NoSuchElementException("Job $id no longer exists.")
        require(text.isNotBlank()) { "Paste the posting text first." }
        val capture = mapOf("text" to text.trim(), "html" to null, "captured_at" to now, "via" to via)
        return planUpdate(sub, existing, capture, "", emptyList(), now)
    }

    fun checkTransition(existing: Opportunity?, id: String, sub: String, from: Set<OpportunityStatus>, to: OpportunityStatus) {
        require(to in PHONE_STATES) { "The phone can't set a job to '${to.key}'." }
        if (existing == null) throw NoSuchElementException("Job $id no longer exists.")
        if (existing.userId != sub) throw SecurityException("Opportunity $id belongs to a different user")
        if (existing.status !in from) {
            throw IllegalStateException("This job is now '${existing.statusText}', so it was not changed to '${to.key}'.")
        }
    }

    /** Most recently changed first (ISO timestamps sort as text). */
    fun sortForDisplay(list: List<Opportunity>): List<Opportunity> =
        list.sortedWith(compareByDescending<Opportunity> { it.updatedAt.ifEmpty { it.createdAt } }.thenBy { it.id })
}

class FirestoreOpportunityStore(private val db: () -> FirebaseFirestore) : OpportunityStore {
    private fun collection(): CollectionReference = db().collection("opportunities")

    override fun observe(sub: String): Flow<List<Opportunity>> = callbackFlow {
        val registration = collection().whereEqualTo("user_id", sub).addSnapshotListener { snap, error ->
            if (error != null) {
                close(error)
                return@addSnapshotListener
            }
            val list = snap?.documents.orEmpty().map { Opportunity(it.id, FirestoreJson.toJsonObject(it.data)) }
            trySend(OpportunityRules.sortForDisplay(list))
        }
        awaitClose { registration.remove() }
    }

    override suspend fun get(sub: String, id: String): Opportunity? {
        val snap = collection().document(id).get().await()
        if (!snap.exists()) return null
        val opp = Opportunity(snap.id, FirestoreJson.toJsonObject(snap.data))
        if (opp.userId != sub) throw SecurityException("Opportunity $id belongs to a different user")
        return opp
    }

    override suspend fun capture(sub: String, request: CaptureRequest): CaptureOutcome {
        val ref = collection().document(OpportunityRules.idFor(sub, request))
        val firestore = db()
        return firestore.runTransaction { tx ->
            val snap = tx.get(ref)
            val existing = if (snap.exists()) Opportunity(snap.id, FirestoreJson.toJsonObject(snap.data)) else null
            val plan = OpportunityRules.planCapture(sub, request, existing, Timestamp.now())
            plan.fields?.let { if (plan.merge) tx.set(ref, it, SetOptions.merge()) else tx.set(ref, it) }
            plan.outcome
        }.await()
    }

    override suspend fun attachCapture(sub: String, id: String, text: String, via: String): CaptureOutcome {
        val ref = collection().document(id)
        return db().runTransaction { tx ->
            val snap = tx.get(ref)
            val existing = if (snap.exists()) Opportunity(snap.id, FirestoreJson.toJsonObject(snap.data)) else null
            val plan = OpportunityRules.planAttach(sub, existing, id, text, via, Timestamp.now())
            plan.fields?.let { tx.set(ref, it, SetOptions.merge()) }
            plan.outcome
        }.await()
    }

    override suspend fun transition(
        sub: String,
        id: String,
        from: Set<OpportunityStatus>,
        to: OpportunityStatus,
        fields: Map<String, Any?>,
    ): Opportunity {
        val ref = collection().document(id)
        db().runTransaction { tx ->
            val snap = tx.get(ref)
            val existing = if (snap.exists()) Opportunity(snap.id, FirestoreJson.toJsonObject(snap.data)) else null
            OpportunityRules.checkTransition(existing, id, sub, from, to)
            tx.update(ref, fields + mapOf("status" to to.key, "updated_at" to Timestamp.now()))
            null
        }.await()
        return get(sub, id) ?: throw NoSuchElementException("Job $id no longer exists.")
    }

    override suspend fun loadSession(sub: String, id: String): JsonObject? {
        get(sub, id) ?: return null
        val snap = collection().document(id).collection("state").document("session").get().await()
        return if (snap.exists()) FirestoreJson.toJsonObject(snap.data) else null
    }
}
