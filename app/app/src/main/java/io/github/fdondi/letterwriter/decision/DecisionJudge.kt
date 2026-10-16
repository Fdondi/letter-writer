package io.github.fdondi.letterwriter.decision

import io.github.fdondi.letterwriter.core.PyText
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.textOrEmpty
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.math.roundToInt

data class DecisionStatus(val available: Boolean, val device: String, val detail: String)

/** Decision-model rescoring of one reranked job (desktop `apply_laya_rag_scores` fields). */
data class RagJudgement(
    val llmScore: Int,
    val score: Int,
    val source: String,
    val decisionScore: Int? = null,
    val confidence: Double? = null,
    val device: String? = null,
    val model: String? = null,
    val error: String? = null,
) {
    companion object {
        const val SOURCE_LLM = "llm"
        const val SOURCE_DECISION_MODEL = "decision_model"
    }
}

/** Feedback item keys set by the decision model, e.g. `decision_verdict`. */
object DecisionKeys {
    const val VERDICT = "decision_verdict"
    const val VALID_PROBABILITY = "decision_valid_probability"
    const val CONFIDENCE = "decision_confidence"
    const val MODEL = "decision_model"
    const val DEVICE = "decision_device"
    const val ERROR = "decision_error"
    const val RESTORED = "decision_restored"

    const val VERDICT_VALID = "valid"
    const val VERDICT_INVALID = "invalid"
    const val VERDICT_UNSCORED = "unscored"

    /** Scored, but no hide threshold is set yet, so the comment stays visible. */
    const val VERDICT_UNCALIBRATED = "uncalibrated"
}

/**
 * Ports `laya_judge.py` onto [DecisionModelClient].
 *
 * Differences, all because Jev's `noul` answer has only a probability:
 * the desktop hides a comment when probability < 0.40 AND Laya confidence >= 0.55.
 * Here a comment is hidden when probability < [hideBelow]; with no threshold set
 * the verdict is `uncalibrated` and nothing is hidden.
 */
class DecisionJudge(private val prompts: QuestionSource) {
    fun interface QuestionSource {
        fun questions(): JsonObject
    }

    private val rag: JsonObject get() = prompts.questions()["rag"] as JsonObject
    private val feedback: JsonObject get() = prompts.questions()["feedback"] as JsonObject

    suspend fun applyRagScores(
        client: DecisionModelClient?,
        unavailableDetail: String,
        jobText: String,
        reranked: Map<String, Pair<Int, String>>,
    ): Pair<DecisionStatus, Map<String, RagJudgement>> {
        if (client == null) {
            val status = DecisionStatus(false, "", unavailableDetail)
            return status to reranked.mapValues { (_, v) -> RagJudgement(v.first, v.first, RagJudgement.SOURCE_LLM, error = unavailableDetail) }
        }
        val status = DecisionStatus(true, client.device, "Decision model at ${client.device}")
        val out = LinkedHashMap<String, RagJudgement>()
        for ((company, v) in reranked) {
            val (llmScore, candidateJob) = v
            out[company] = try {
                val r = client.decide(ragState(jobText, company, candidateJob), rag)
                val (expected, confidence) = DecisionModelClient.scoreAnswer(r, "similarity")
                val mapped = mapSimilarityScore(expected)
                RagJudgement(llmScore, mapped, RagJudgement.SOURCE_DECISION_MODEL, mapped, confidence, client.device, r.model)
            } catch (e: Exception) {
                RagJudgement(llmScore, llmScore, RagJudgement.SOURCE_LLM, error = "${e::class.simpleName}: ${e.message}")
            }
        }
        return status to out
    }

    /** Marks PLEASE_FIX comments; invalid ones stay on the item. Returns the annotated feedback map. */
    suspend fun annotateFeedbackValidity(
        client: DecisionModelClient?,
        unavailableDetail: String,
        feedbackByCategory: JsonObject,
        letter: String,
        hideBelow: Double?,
    ): Pair<DecisionStatus, JsonObject> {
        if (client == null) {
            return DecisionStatus(false, "", unavailableDetail) to stampUnscored(feedbackByCategory, unavailableDetail)
        }
        val status = DecisionStatus(true, client.device, "Decision model at ${client.device}")
        val out = LinkedHashMap<String, JsonElement>()
        for ((category, items) in feedbackByCategory) {
            if (items !is JsonArray) {
                out[category] = items
                continue
            }
            out[category] = JsonArray(
                items.map { el ->
                    val item = el.asObjectOrNull() ?: return@map el
                    if (!isPleaseFix(item) || item.textOrEmpty("observation").isBlank() || isRestored(item)) return@map el
                    val m = item.toMutableMap()
                    try {
                        val r = client.decide(feedbackState(letter, item, category), feedback)
                        val p = DecisionModelClient.noulAnswer(r, "grounded")
                        m[DecisionKeys.VERDICT] = JsonPrimitive(
                            when {
                                hideBelow == null -> DecisionKeys.VERDICT_UNCALIBRATED
                                p < hideBelow -> DecisionKeys.VERDICT_INVALID
                                else -> DecisionKeys.VERDICT_VALID
                            },
                        )
                        m[DecisionKeys.VALID_PROBABILITY] = JsonPrimitive(p)
                        m[DecisionKeys.MODEL] = JsonPrimitive(r.model)
                        m[DecisionKeys.DEVICE] = JsonPrimitive(client.device)
                    } catch (e: Exception) {
                        m[DecisionKeys.VERDICT] = JsonPrimitive(DecisionKeys.VERDICT_UNSCORED)
                        m[DecisionKeys.ERROR] = JsonPrimitive("${e::class.simpleName}: ${e.message}")
                    }
                    JsonObject(m)
                },
            )
        }
        return status to JsonObject(out)
    }

    companion object {
        fun isPleaseFix(item: JsonObject) = item.textOrEmpty("type").uppercase() == "PLEASE_FIX"

        fun isRestored(item: JsonObject) = item[DecisionKeys.RESTORED].asBooleanOrNull() == true

        /** `comment_is_laya_hidden`. */
        fun isHidden(item: JsonObject): Boolean =
            !isRestored(item) && item[DecisionKeys.VERDICT].asStringOrNull().orEmpty().trim().lowercase() == DecisionKeys.VERDICT_INVALID

        /** 0..4 expectation onto the 1..10 rubric (criteria line up with 2, 4, 6, 8, 10). */
        fun mapSimilarityScore(expected: Double): Int {
            val clamped = expected.coerceIn(0.0, 4.0)
            return pyRound(2.0 + clamped * 2.0).coerceIn(1, 10)
        }

        /** Python `round` (banker's rounding). */
        private fun pyRound(x: Double): Int = Math.rint(x).roundToInt()

        fun ragState(targetJob: String, company: String, candidateJob: String): String =
            "Candidate company: $company\n" +
                "Candidate job opening:\n${PyText.take(candidateJob, 800)}\n\n" +
                "Target job opening:\n${PyText.take(targetJob, 800)}"

        fun feedbackState(letter: String, item: JsonObject, category: String): String {
            val quote = (item.textOrEmpty("matched_text").ifEmpty { item.textOrEmpty("quote") }).trim()
            val observation = item.textOrEmpty("observation").trim()
            val window = letterWindow(letter, quote)
            return "Feedback comment:\n${PyText.take(observation, 800)}\n\n" +
                "Quoted span:\n${PyText.take(quote, 500)}\n\n" +
                "Topic: $category\n\n" +
                "Letter text:\n${PyText.take(window, 1500)}"
        }

        private fun letterWindow(letter: String, quote: String): String {
            if (letter.isEmpty()) return ""
            if (quote.isNotEmpty()) {
                val at = PyText.find(letter, quote)
                if (at >= 0) {
                    return PyText.slice(letter, maxOf(0, at - 400), at + PyText.length(quote) + 800)
                }
            }
            return PyText.take(letter, 1500)
        }

        /** `_stamp_feedback_unscored`: items that already have a verdict keep it. */
        fun stampUnscored(feedbackByCategory: JsonObject, detail: String): JsonObject =
            JsonObject(
                feedbackByCategory.mapValues { (_, items) ->
                    if (items !is JsonArray) return@mapValues items
                    JsonArray(
                        items.map { el ->
                            val item = el.asObjectOrNull() ?: return@map el
                            if (!isPleaseFix(item) || item[DecisionKeys.VERDICT].asStringOrNull().orEmpty().isNotEmpty()) return@map el
                            JsonObject(
                                item + mapOf(
                                    DecisionKeys.VERDICT to JsonPrimitive(DecisionKeys.VERDICT_UNSCORED),
                                    DecisionKeys.ERROR to JsonPrimitive(detail),
                                ),
                            )
                        },
                    )
                },
            )
    }
}
