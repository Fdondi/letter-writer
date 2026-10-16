package io.github.fdondi.letterwriter.decision

import io.github.fdondi.letterwriter.core.DecisionModelSettings
import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.llm.DECISION_MODEL_VENDOR
import io.github.fdondi.letterwriter.llm.UsageTotals
import io.github.fdondi.letterwriter.llm.currentUsageCollector
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URI

/** The decision model could not answer; the message is safe to show in the UI. */
class DecisionModelUnavailable(message: String, cause: Throwable? = null) : RuntimeException(message, cause)

/** One `POST /v1/systemone` response (TypeSafe wire format: `model`, `answers`, `usage`). */
data class DecisionResponse(val model: String, val answers: JsonObject, val inputTokens: Long)

/**
 * TypeSafe System One client. Jev is the configured backend; any server speaking
 * the same wire format (an Ollaya `/v1/systemone`) works with a different base URL.
 */
class DecisionModelClient(
    private val settings: DecisionModelSettings,
    private val apiKey: String,
) {
    val device: String = runCatching { URI(settings.baseUrl).host }.getOrNull() ?: settings.baseUrl

    suspend fun decide(state: String, questions: JsonObject): DecisionResponse {
        val body = buildJsonObject {
            put("model", settings.model)
            put("state", state)
            put("questions", questions)
        }
        val raw = try {
            Http.postJson("Decision model", "${settings.baseUrl}/v1/systemone", body, mapOf("Authorization" to "Bearer $apiKey"))
        } catch (e: Exception) {
            throw DecisionModelUnavailable("Decision model request to ${settings.baseUrl} failed: ${e.message}", e)
        }
        val obj = raw.asObjectOrNull() ?: throw DecisionModelUnavailable("Decision model response was not a JSON object.")
        val model = obj["model"].asStringOrNull().orEmpty().ifEmpty { settings.model }
        val inputTokens = obj["usage"].asObjectOrNull()?.get("input_tokens").asLongOrNull() ?: 0L
        record(model, inputTokens)
        return DecisionResponse(model, obj["answers"].asObjectOrNull() ?: JsonObject(emptyMap()), inputTokens)
    }

    private suspend fun record(model: String, inputTokens: Long) {
        val collector = currentUsageCollector()
        val price = PRICE_PER_MTOK_INPUT[model]
        if (price == null) collector.noteUnpriced(DECISION_MODEL_VENDOR, model)
        val cost = inputTokens / 1e6 * (price ?: 0.0)
        collector.add(DECISION_MODEL_VENDOR, UsageTotals(cost = cost, inputTokens = inputTokens, requests = 1))
    }

    companion object {
        /** TypeSafe list price (docs.typesafe.ai/models): input tokens only, output free. */
        val PRICE_PER_MTOK_INPUT = mapOf(
            "jev-1.13.0" to 0.042,
            "jev-latest" to 0.042,
            "jev-preview" to 0.042,
        )

        /** `answers.similarity` of a score question: (expected 0..n-1, confidence). */
        fun scoreAnswer(r: DecisionResponse, id: String): Pair<Double, Double?> {
            val a = r.answers[id].asObjectOrNull() ?: JsonObject(emptyMap())
            val score = a["score"].asDoubleOrNull() ?: throw DecisionModelUnavailable("Decision model answer '$id' missing score: $a")
            return score to a["confidence"].asDoubleOrNull()
        }

        /** `answers.grounded` of a noul question: probability of yes. TypeSafe sends no confidence for noul. */
        fun noulAnswer(r: DecisionResponse, id: String): Double {
            val a = r.answers[id].asObjectOrNull() ?: JsonObject(emptyMap())
            return a["noul"].asDoubleOrNull() ?: throw DecisionModelUnavailable("Decision model answer '$id' missing noul: $a")
        }
    }
}
