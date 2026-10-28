package io.github.fdondi.letterwriter.data

import com.google.firebase.Timestamp
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject

/**
 * `opportunities` kept in memory, with the same [OpportunityRules] as Firestore: demo mode and
 * tests. [sessions] holds `state/session` per job (written only by whoever seeds the store, like
 * the desktop batch does for Firestore).
 */
class InMemoryOpportunityStore(
    jobs: List<Opportunity> = emptyList(),
    sessions: Map<String, JsonObject> = emptyMap(),
    private val now: () -> Timestamp = { Timestamp.now() },
) : OpportunityStore {
    private val docs = MutableStateFlow(jobs.associateBy { it.id })
    private val states = sessions.toMutableMap()
    private val lock = Mutex()

    override fun observe(sub: String): Flow<List<Opportunity>> =
        docs.map { all -> OpportunityRules.sortForDisplay(all.values.filter { it.userId == sub }) }

    override suspend fun get(sub: String, id: String): Opportunity? {
        val opp = docs.value[id] ?: return null
        if (opp.userId != sub) throw SecurityException("Opportunity $id belongs to a different user")
        return opp
    }

    override suspend fun capture(sub: String, request: CaptureRequest): CaptureOutcome = lock.withLock {
        val id = OpportunityRules.idFor(sub, request)
        val plan = OpportunityRules.planCapture(sub, request, docs.value[id], now())
        apply(plan)
        plan.outcome
    }

    override suspend fun attachCapture(sub: String, id: String, text: String, via: String): CaptureOutcome = lock.withLock {
        val plan = OpportunityRules.planAttach(sub, docs.value[id], id, text, via, now())
        apply(plan)
        plan.outcome
    }

    override suspend fun transition(
        sub: String,
        id: String,
        from: Set<OpportunityStatus>,
        to: OpportunityStatus,
        fields: Map<String, Any?>,
    ): Opportunity = lock.withLock {
        val existing = docs.value[id]
        OpportunityRules.checkTransition(existing, id, sub, from, to)
        val updated = merge(existing!!, fields + mapOf("status" to to.key, "updated_at" to now()))
        docs.value = docs.value + (id to updated)
        updated
    }

    override suspend fun loadSession(sub: String, id: String): JsonObject? {
        get(sub, id) ?: return null
        return states[id]
    }

    private fun apply(plan: CapturePlan) {
        val fields = plan.fields ?: return
        val existing = docs.value[plan.id]
        val doc = if (existing == null || !plan.merge) {
            Opportunity(plan.id, FirestoreJson.toJsonObject(fields))
        } else {
            merge(existing, fields)
        }
        docs.value = docs.value + (plan.id to doc)
    }

    private fun merge(existing: Opportunity, fields: Map<String, Any?>): Opportunity =
        Opportunity(existing.id, JsonObject(existing.data + FirestoreJson.toJsonObject(fields)))
}
