package io.github.fdondi.letterwriter.cost

import io.github.fdondi.letterwriter.auth.AuthGateway
import io.github.fdondi.letterwriter.auth.BigQueryAuth
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.llm.UsageCollector
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.time.Instant
import java.util.UUID

sealed interface CostSyncState {
    data object Idle : CostSyncState
    data object Syncing : CostSyncState
    data class Synced(val at: Instant) : CostSyncState

    /** Rows stay queued on the phone; [message] says why they did not reach BigQuery. */
    data class Failed(val message: String, val needsConsent: BigQueryAuth.NeedsConsent? = null) : CostSyncState
}

/**
 * Same rows as the desktop `track_api_cost` + `flush_costs_to_bigquery`.
 *
 * Rows are appended to a local queue file before any network call and removed only
 * after BigQuery accepts them, so a crash or an offline phone never drops a cost.
 */
class CostRecorder(
    private val queueFile: File,
    private val auth: AuthGateway,
    private val bigQuery: BigQueryApi,
) {
    private val mutex = Mutex()
    private val _state = MutableStateFlow<CostSyncState>(CostSyncState.Idle)
    val state: StateFlow<CostSyncState> = _state.asStateFlow()

    private val _pending = MutableStateFlow(0)
    val pendingRows: StateFlow<Int> = _pending.asStateFlow()

    private val _unpriced = MutableStateFlow<List<String>>(emptyList())

    /** `vendor/model` ids used this session that have no price in the catalog (recorded as $0). */
    val unpricedModels: StateFlow<List<String>> = _unpriced.asStateFlow()

    suspend fun init() = mutex.withLock { _pending.value = readQueue().size }

    /** One row per vendor with spend, like `phased_service._track_phase_costs` (cost > 0 only). */
    suspend fun recordPhase(userId: String, collector: UsageCollector) {
        val unpriced = collector.unpricedModels()
        if (unpriced.isNotEmpty()) _unpriced.value = (_unpriced.value + unpriced).distinct()
        val rows = collector.totals().filter { it.value.cost > 0 }.map { (vendor, u) ->
            buildJsonObject {
                put("timestamp", Instant.now().toString())
                put("user_id", userId)
                put("phase", collector.phase)
                put("vendor", vendor)
                put("cost", u.cost)
                put("request_count", 1)
                put("input_tokens", u.inputTokens)
                put("output_tokens", u.outputTokens)
                if (u.searchQueries > 0) put("search_queries", u.searchQueries)
            }
        }
        enqueue(rows)
    }

    suspend fun recordTranslation(userId: String, characterCount: Int) {
        val cost = characterCount / 1_000_000.0 * 20.0
        enqueue(
            listOf(
                buildJsonObject {
                    put("timestamp", Instant.now().toString())
                    put("user_id", userId)
                    put("phase", "translate")
                    put("vendor", "google_translate")
                    put("cost", cost)
                    put("request_count", 1)
                    put("character_count", characterCount)
                },
            ),
        )
    }

    private suspend fun enqueue(rows: List<JsonObject>) {
        if (rows.isEmpty()) return
        mutex.withLock {
            queueFile.parentFile?.mkdirs()
            queueFile.appendText(
                rows.joinToString("") { row ->
                    val entry = buildJsonObject {
                        put("insert_id", UUID.randomUUID().toString())
                        put("row", row)
                    }
                    Json.codec.encodeToString(JsonObject.serializer(), entry) + "\n"
                },
            )
            _pending.value = readQueue().size
        }
    }

    /**
     * Sends queued rows to `letter_writer.api_costs`. With [savingUserId] set, every row gets
     * `document_saved` = (row user == saver), as in desktop `flush_on_letter_completion`.
     *
     * Never throws (it runs from screens and app start): a failure ends up in [state].
     */
    suspend fun flush(savingUserId: String? = null) {
        try {
            flushQueued(savingUserId)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.value = CostSyncState.Failed("Cost upload failed: ${e.message ?: e::class.simpleName}")
        }
    }

    private suspend fun flushQueued(savingUserId: String?) = mutex.withLock {
        val queue = readQueue()
        if (queue.isEmpty()) {
            _state.value = CostSyncState.Synced(Instant.now())
            return@withLock
        }
        _state.value = CostSyncState.Syncing
        val authResult = try {
            auth.bigQueryAuth()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.value = CostSyncState.Failed("BigQuery authorization failed: ${e.message}")
            return@withLock
        }
        val token = when (val a = authResult) {
            is BigQueryAuth.Token -> a.accessToken
            is BigQueryAuth.NeedsConsent -> {
                _state.value = CostSyncState.Failed("Allow BigQuery access to upload ${queue.size} queued cost rows", a)
                return@withLock
            }
        }
        val rows = queue.map { q ->
            val row = if (savingUserId != null) {
                JsonObject(q.row + ("document_saved" to JsonPrimitive(q.row["user_id"].asStringOrNull() == savingUserId)))
            } else {
                q.row
            }
            q.insertId to row
        }
        val failed = try {
            bigQuery.insertAll(token, TABLE, rows)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.value = CostSyncState.Failed("BigQuery insert failed: ${e.message}")
            return@withLock
        }
        val remaining = queue.filterIndexed { i, _ -> i in failed }
        writeQueue(remaining)
        _pending.value = remaining.size
        _state.value = if (failed.isEmpty()) {
            CostSyncState.Synced(Instant.now())
        } else {
            CostSyncState.Failed("BigQuery rejected ${failed.size} rows: ${failed.values.first()}")
        }
    }

    /** Desktop `get_user_monthly_cost`, same four queries. */
    suspend fun monthlySummary(userId: String, monthsBack: Int = 1): MonthlyCost {
        val token = when (val a = auth.bigQueryAuth()) {
            is BigQueryAuth.Token -> a.accessToken
            is BigQueryAuth.NeedsConsent -> throw BigQueryConsentRequired(a)
        }
        val t = bigQuery.tableRef(TABLE)
        val where = "WHERE user_id = @user_id\n  AND timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL @months_back MONTH))"
        val params = listOf(QueryParam("user_id", "STRING", userId), QueryParam("months_back", "INT64", monthsBack.toString()))

        val phaseRows = bigQuery.query(
            token,
            "SELECT phase, SUM(cost) as total_cost, SUM(request_count) as total_requests, " +
                "SUM(COALESCE(input_tokens, 0)) as input_tokens, SUM(COALESCE(output_tokens, 0)) as output_tokens " +
                "FROM $t $where GROUP BY phase",
            params,
        )
        val letterCount = bigQuery.query(
            token,
            "SELECT COUNT(*) as letter_count FROM $t WHERE user_id = @user_id AND phase = 'extract' " +
                "AND timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL @months_back MONTH))",
            params,
        ).firstOrNull()?.get("letter_count")?.toLongOrNull() ?: 0
        val vendorRows = bigQuery.query(
            token,
            "SELECT vendor, SUM(cost) as total_cost, SUM(request_count) as total_requests, " +
                "SUM(COALESCE(input_tokens, 0)) as input_tokens, SUM(COALESCE(output_tokens, 0)) as output_tokens, " +
                "COUNTIF(phase = 'refine') as letter_count FROM $t $where GROUP BY vendor",
            params,
        )
        val vendorPhaseRows = bigQuery.query(
            token,
            "SELECT vendor, phase, SUM(cost) as total_cost FROM $t $where GROUP BY vendor, phase",
            params,
        )

        fun line(r: Map<String, String?>, letters: Long) = CostLine(
            totalCost = r["total_cost"]?.toDoubleOrNull() ?: 0.0,
            requestCount = r["total_requests"]?.toLongOrNull() ?: 0,
            inputTokens = r["input_tokens"]?.toLongOrNull() ?: 0,
            outputTokens = r["output_tokens"]?.toLongOrNull() ?: 0,
            letterCount = letters,
        )
        val byPhase = phaseRows.associate { (it["phase"] ?: "unknown") to line(it, letterCount) }
        val byVendor = vendorRows.associate { (it["vendor"] ?: "unknown") to line(it, it["letter_count"]?.toLongOrNull() ?: 0) }
        val byVendorPhase = LinkedHashMap<String, MutableMap<String, Double>>()
        vendorPhaseRows.forEach { r ->
            byVendorPhase.getOrPut(r["vendor"] ?: "unknown") { LinkedHashMap() }[r["phase"] ?: "unknown"] =
                r["total_cost"]?.toDoubleOrNull() ?: 0.0
        }
        return MonthlyCost(
            monthsBack = monthsBack,
            totalCost = byPhase.values.sumOf { it.totalCost },
            totalRequests = byPhase.values.sumOf { it.requestCount },
            letterCount = letterCount,
            byPhase = byPhase,
            byVendor = byVendor,
            byVendorPhase = byVendorPhase,
        )
    }

    /** Spend still queued on the phone (not yet in BigQuery). */
    suspend fun pendingCost(): Double = mutex.withLock { readQueue().sumOf { it.row["cost"].asDoubleOrNull() ?: 0.0 } }

    private data class Queued(val insertId: String, val row: JsonObject)

    /**
     * Lines that don't parse (a write cut short by a crash or a full disk) are moved to
     * `<queue>.bad` and skipped, so one broken line can't block every later upload.
     */
    private fun readQueue(): List<Queued> {
        if (!queueFile.isFile) return emptyList()
        val good = ArrayList<Queued>()
        val bad = ArrayList<String>()
        for (line in queueFile.readLines()) {
            if (line.isBlank()) continue
            val parsed = runCatching {
                val o = Json.parse(line) as JsonObject
                Queued((o["insert_id"] as JsonPrimitive).content, o["row"] as JsonObject)
            }.getOrNull()
            if (parsed != null) good += parsed else bad += line
        }
        if (bad.isNotEmpty()) {
            File(queueFile.parentFile, queueFile.name + ".bad").appendText(bad.joinToString("") { it + "\n" })
            writeQueue(good)
        }
        return good
    }

    private fun writeQueue(items: List<Queued>) {
        val tmp = File(queueFile.parentFile, queueFile.name + ".tmp")
        tmp.writeText(
            items.joinToString("") { q ->
                Json.codec.encodeToString(
                    JsonObject.serializer(),
                    buildJsonObject { put("insert_id", q.insertId); put("row", q.row) },
                ) + "\n"
            },
        )
        if (!tmp.renameTo(queueFile)) throw IllegalStateException("Could not update the cost queue file ${queueFile.path}")
    }

    companion object {
        const val TABLE = "api_costs"
    }
}

class BigQueryConsentRequired(val consent: BigQueryAuth.NeedsConsent) :
    IllegalStateException("Allow BigQuery access to read your costs")

data class CostLine(
    val totalCost: Double,
    val requestCount: Long,
    val inputTokens: Long,
    val outputTokens: Long,
    val letterCount: Long,
) {
    val costPerLetter: Double? get() = if (letterCount > 0) totalCost / letterCount else null
}

data class MonthlyCost(
    val monthsBack: Int,
    val totalCost: Double,
    val totalRequests: Long,
    val letterCount: Long,
    val byPhase: Map<String, CostLine>,
    val byVendor: Map<String, CostLine>,
    val byVendorPhase: Map<String, Map<String, Double>>,
)
