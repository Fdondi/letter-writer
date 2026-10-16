package io.github.fdondi.letterwriter.llm

import kotlinx.coroutines.withContext
import kotlin.coroutines.AbstractCoroutineContextElement
import kotlin.coroutines.CoroutineContext
import kotlin.coroutines.coroutineContext

data class UsageTotals(
    val cost: Double = 0.0,
    val inputTokens: Long = 0,
    val outputTokens: Long = 0,
    val cachedTokens: Long = 0,
    val searchQueries: Long = 0,
    val requests: Int = 0,
) {
    operator fun plus(o: UsageTotals) = UsageTotals(
        cost + o.cost,
        inputTokens + o.inputTokens,
        outputTokens + o.outputTokens,
        cachedTokens + o.cachedTokens,
        searchQueries + o.searchQueries,
        requests + o.requests,
    )
}

/**
 * Collects LLM usage for one cost phase (`extract`, `draft`, ...).
 *
 * Every client call must run inside [withUsagePhase]; a call outside one throws
 * instead of spending money that never reaches the cost table.
 */
class UsageCollector(val phase: String) : AbstractCoroutineContextElement(UsageCollector) {
    companion object Key : CoroutineContext.Key<UsageCollector>

    private val byVendor = LinkedHashMap<String, UsageTotals>()
    private val unpriced = LinkedHashSet<String>()

    /** [vendorKey] is the cost-table `vendor` value: a [ModelVendor.key] or [DECISION_MODEL_VENDOR]. */
    @Synchronized
    fun add(vendorKey: String, usage: UsageTotals) {
        byVendor[vendorKey] = (byVendor[vendorKey] ?: UsageTotals()) + usage
    }

    @Synchronized
    fun noteUnpriced(vendorKey: String, model: String) {
        unpriced.add("$vendorKey/$model")
    }

    @Synchronized
    fun totals(): Map<String, UsageTotals> = LinkedHashMap(byVendor)

    /** `vendor/model` ids that had no price entry; their calls were counted as $0. */
    @Synchronized
    fun unpricedModels(): List<String> = unpriced.toList()
}

const val DECISION_MODEL_VENDOR = "decision_model"

suspend fun <T> withUsagePhase(collector: UsageCollector, block: suspend () -> T): T =
    withContext(collector) { block() }

suspend fun currentUsageCollector(): UsageCollector =
    coroutineContext[UsageCollector]
        ?: throw IllegalStateException("LLM call made outside a cost phase; its cost would not be recorded")
