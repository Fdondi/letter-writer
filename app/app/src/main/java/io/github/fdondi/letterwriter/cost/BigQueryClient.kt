package io.github.fdondi.letterwriter.cost

import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** The two BigQuery calls the cost table needs. Tests use an in-memory one. */
interface BigQueryApi {
    /** Returns the indexes of rows BigQuery rejected, with the reason. */
    suspend fun insertAll(token: String, table: String, rows: List<Pair<String, JsonObject>>): Map<Int, String>

    /** Runs a standard-SQL query with named parameters; returns rows as column-name maps of raw strings. */
    suspend fun query(token: String, sql: String, params: List<QueryParam>): List<Map<String, String?>>

    fun tableRef(table: String): String
}

/** Minimal BigQuery REST client (insertAll + jobs.query) authorised with the user's OAuth token. */
class BigQueryClient(private val project: String, private val dataset: String) : BigQueryApi {
    private val base = "https://bigquery.googleapis.com/bigquery/v2/projects/$project"

    override suspend fun insertAll(token: String, table: String, rows: List<Pair<String, JsonObject>>): Map<Int, String> {
        val body = buildJsonObject {
            put("skipInvalidRows", false)
            put("ignoreUnknownValues", false)
            put(
                "rows",
                buildJsonArray {
                    rows.forEach { (id, json) -> add(buildJsonObject { put("insertId", id); put("json", json) }) }
                },
            )
        }
        val resp = Http.postJson("BigQuery", "$base/datasets/$dataset/tables/$table/insertAll", body, auth(token))
            .asObjectOrNull() ?: JsonObject(emptyMap())
        val failed = LinkedHashMap<Int, String>()
        for (e in resp["insertErrors"].asArrayOrNull().orEmpty()) {
            val o = e.asObjectOrNull() ?: continue
            val index = o["index"].asLongOrNull()?.toInt() ?: continue
            val reason = o["errors"].asArrayOrNull().orEmpty().joinToString("; ") {
                val err = it.asObjectOrNull()
                "${err?.get("reason").asStringOrNull()}: ${err?.get("message").asStringOrNull()}"
            }
            failed[index] = reason
        }
        return failed
    }

    override suspend fun query(token: String, sql: String, params: List<QueryParam>): List<Map<String, String?>> {
        val body = buildJsonObject {
            put("query", sql)
            put("useLegacySql", false)
            put("parameterMode", "NAMED")
            put("timeoutMs", 30000)
            put(
                "queryParameters",
                buildJsonArray {
                    params.forEach { p ->
                        add(
                            buildJsonObject {
                                put("name", p.name)
                                put("parameterType", buildJsonObject { put("type", p.type) })
                                put("parameterValue", buildJsonObject { put("value", p.value) })
                            },
                        )
                    }
                },
            )
        }
        var resp = Http.postJson("BigQuery", "$base/queries", body, auth(token)).asObjectOrNull()
            ?: throw IllegalStateException("BigQuery query returned a non-object response")
        var attempts = 0
        while (resp["jobComplete"].asBooleanOrNull() != true) {
            if (++attempts > 30) throw IllegalStateException("BigQuery query did not finish in time")
            delay(1000)
            val ref = resp["jobReference"].asObjectOrNull()
                ?: throw IllegalStateException("BigQuery query is incomplete and has no job reference")
            val jobId = ref["jobId"].asStringOrNull()
            val location = ref["location"].asStringOrNull()
            val url = "$base/queries/$jobId?timeoutMs=10000" + (location?.let { "&location=$it" } ?: "")
            resp = Http.getJson("BigQuery", url, auth(token)).asObjectOrNull()
                ?: throw IllegalStateException("BigQuery getQueryResults returned a non-object response")
        }
        val fields = resp["schema"].asObjectOrNull()?.get("fields").asArrayOrNull().orEmpty()
            .map { it.asObjectOrNull()?.get("name").asStringOrNull().orEmpty() }
        return resp["rows"].asArrayOrNull().orEmpty().map { row ->
            val cells = row.asObjectOrNull()?.get("f").asArrayOrNull().orEmpty()
            fields.mapIndexed { i, name -> name to cells.getOrNull(i).asObjectOrNull()?.get("v").asStringOrNull() }.toMap()
        }
    }

    override fun tableRef(table: String) = "`$project.$dataset.$table`"

    private fun auth(token: String) = mapOf("Authorization" to "Bearer $token")
}

data class QueryParam(val name: String, val type: String, val value: String)
