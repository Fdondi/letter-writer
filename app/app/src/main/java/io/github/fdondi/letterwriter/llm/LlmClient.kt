package io.github.fdondi.letterwriter.llm

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/** Same contract as Python `BaseClient.call`; see `clients/base.py` for the cache-prefix semantics. */
interface LlmClient {
    val vendor: ModelVendor

    suspend fun call(
        role: RoleRef,
        system: String,
        userMessages: List<String>,
        search: Boolean = false,
        responseFormat: JsonObject? = null,
        cachePrefix: String? = null,
        systemCachePrefix: String? = null,
        promptCacheKey: String? = null,
    ): String
}

suspend fun LlmClient.call(
    role: ModelRole,
    system: String,
    userMessages: List<String>,
    search: Boolean = false,
    responseFormat: JsonObject? = null,
    cachePrefix: String? = null,
    systemCachePrefix: String? = null,
    promptCacheKey: String? = null,
): String = call(role.ref(), system, userMessages, search, responseFormat, cachePrefix, systemCachePrefix, promptCacheKey)

data class ResolvedModel(val model: String, val thinking: Map<String, JsonElement>)

abstract class BaseLlmClient(
    final override val vendor: ModelVendor,
    protected val catalog: VendorCatalog,
    private val overrides: VendorRoleOverrides,
    protected val apiKey: String,
) : LlmClient {
    /** Applies the user's bound override, then the catalog role entry (Python `resolve_effective_model_role`). */
    protected fun resolve(role: RoleRef): ResolvedModel {
        val effective = when (role) {
            is RoleRef.Role -> ModelOverrides.resolveClientModelRole(vendor.key, role.role, overrides)
            is RoleRef.ModelId -> role
        }
        return when (effective) {
            is RoleRef.ModelId -> {
                val (id, suffix) = ModelOverrides.splitModelIdAndThinking(effective.id)
                ResolvedModel(id, ModelOverrides.thinkingConfigForVendor(vendor.key, suffix))
            }
            is RoleRef.Role -> ResolvedModel(catalog.modelForRole(effective.role), catalog.thinkingConfig(effective.role))
        }
    }

    /** Python `BaseClient.track_cost` (cached tokens at `input_cached_mult`). */
    protected suspend fun trackStandard(
        model: String,
        inputTokens: Long,
        outputTokens: Long,
        searchQueries: Long = 0,
        cachedTokens: Long = 0,
    ) {
        val c = catalog.modelCost(model)
        val uncached = maxOf(0, inputTokens - cachedTokens)
        val inputCost = uncached / 1e6 * c.input + cachedTokens / 1e6 * c.input * c.inputCachedMult
        val cost = inputCost + outputTokens / 1e6 * c.output + searchQueries / 1e3 * c.search
        record(model, c.priced, UsageTotals(cost, inputTokens, outputTokens, cachedTokens, searchQueries, 1))
    }

    protected suspend fun record(model: String, priced: Boolean, usage: UsageTotals) {
        val collector = currentUsageCollector()
        if (!priced) collector.noteUnpriced(vendor.key, model)
        collector.add(vendor.key, usage)
    }

    protected fun bearer(): Map<String, String> = mapOf("Authorization" to "Bearer $apiKey")
}

fun mergeSystemCachePrefixIntoSystem(system: String, systemCachePrefix: String?): String {
    val prefix = systemCachePrefix?.trim().orEmpty()
    if (prefix.isEmpty()) return system
    return if (system.isNotEmpty()) "$prefix\n\n$system" else prefix
}
