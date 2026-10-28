package io.github.fdondi.letterwriter.data

import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asLongOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.pyStr
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject

/** `opportunities.status` (OPPORTUNITY_PIPELINE_PLAN.md §1). [UNKNOWN] keeps a value this build doesn't know. */
enum class OpportunityStatus(val key: String) {
    PROPOSED("proposed"),
    SKIPPED("skipped"),
    APPROVED("approved"),
    CAPTURED("captured"),
    RATED("rated"),
    DRAFTING("drafting"),
    READY("ready"),
    FAILED("failed"),
    DONE("done"),
    APPLIED("applied"),
    ARCHIVED("archived"),
    UNKNOWN(""),
    ;

    companion object {
        fun fromKey(key: String?): OpportunityStatus =
            entries.firstOrNull { it != UNKNOWN && it.key == key?.trim()?.lowercase() } ?: UNKNOWN
    }
}

private val STAGE_LABELS = mapOf(
    "applied" to "applied",
    "received" to "received",
    "viewed" to "viewed",
    "forwarded" to "sent to the client",
    "screening" to "screening",
    "interview" to "interview",
    "final" to "final round",
    "offer" to "offer",
)

/** One `opportunities/{id}` document as JSON (Firestore timestamps already ISO strings). */
data class Opportunity(val id: String, val data: JsonObject) {
    private fun text(key: String): String = data[key].asStringOrNull()?.trim().orEmpty()

    private fun strings(key: String): List<String> =
        data[key].asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull()?.trim()?.takeIf(String::isNotEmpty) }

    val status: OpportunityStatus get() = OpportunityStatus.fromKey(data["status"].asStringOrNull())
    val statusText: String get() = text("status")
    val userId: String get() = text("user_id")
    val canonicalKey: String get() = text("canonical_key")
    val source: String get() = text("source")
    val url: String get() = text("url")
    val title: String get() = text("title")
    val company: String get() = text("company")
    val location: String get() = text("location")
    val skipReason: String get() = text("skip_reason")
    val documentId: String? get() = text("document_id").ifEmpty { null }
    val createdAt: String get() = text("created_at")
    val updatedAt: String get() = text("updated_at")

    private val capture: JsonObject? get() = data["capture"].asObjectOrNull()
    val captureText: String get() = capture?.get("text").asStringOrNull().orEmpty()
    val captureVia: String get() = capture?.get("via").asStringOrNull().orEmpty()

    val vendorsRequested: List<String> get() = strings("vendors_requested")
    val vendorsDone: List<String> get() = strings("vendors_done")

    /** Vendor to its error text. */
    val vendorsFailed: Map<String, String>
        get() = data["vendors_failed"].asObjectOrNull().orEmpty()
            .filterValues { it !is JsonNull }
            .mapValues { (_, v) -> v.asStringOrNull() ?: v.pyStr() }

    val inputNeededCount: Int get() = data["input_needed_count"].asLongOrNull()?.toInt() ?: 0
    val fitMatched: List<String> get() = fitList("matched")
    val fitGaps: List<String> get() = fitList("gaps")

    /** The desktop's computed fit (the weighted competence match), 1–5. */
    val fitScore: Double? get() = data["fit_score"].asDoubleOrNull()

    /** The user's per-job override; wins over [fitScore] when set. */
    val fitScoreUser: Double? get() = data["fit_score_user"].asDoubleOrNull()

    /** The rating the desktop sorts the rated queue by: the user's override, else the computed one. */
    val fitScoreEffective: Double? get() = fitScoreUser ?: fitScore
    val costApiUsd: Double? get() = data["cost_api_usd"].asDoubleOrNull()
    val costSubscriptionUsd: Double? get() = data["cost_subscription_estimate_usd"].asDoubleOrNull()

    /** Set by the desktop when you already applied to this company before (another role). */
    val historyNote: String get() = text("history_note")

    private val outcome: JsonObject? get() = data["outcome"].asObjectOrNull()

    /** Praise from the company's mails (a sign of letter quality). */
    val feedbackQuotes: List<String>
        get() = outcome?.get("feedback_quotes").asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull()?.takeIf(String::isNotBlank) }

    /**
     * How far the application got (a sign of job fit), from the replies the desktop read in your
     * mail: "interview ×2 · rejected · praised". Empty when nothing came back yet.
     */
    val outcomeLine: String
        get() {
            val o = outcome ?: return ""
            val stage = o["stage"].asStringOrNull().orEmpty()
            if (stage.isEmpty()) return ""
            val rounds = o["interviews"].asLongOrNull() ?: 0
            val parts = mutableListOf(STAGE_LABELS[stage] ?: stage)
            if (rounds > 1) parts[0] = "${parts[0]} ×$rounds"
            o["result"].asStringOrNull()?.takeIf { it.isNotEmpty() }?.let(parts::add)
            if (o["positive_feedback"].asBooleanOrNull() == true) parts += "praised"
            return parts.joinToString(" · ")
        }

    private val progress: JsonObject? get() = data["progress"].asObjectOrNull()

    /** When the desktop started drafting this job (ISO), from its progress report. */
    val runningSince: String get() = progress?.get("started_at").asStringOrNull().orEmpty()

    /**
     * What the desktop is doing with a `drafting` job, from the progress the batch writes:
     * "Reading the posting", "Researching the company", "Drafting · 3 of 8 vendors done".
     * Empty before the first report (or from a batch that does not report).
     */
    val progressLine: String
        get() {
            val p = progress ?: return ""
            val done = p["vendors_done"].asArrayOrNull().orEmpty().size
            val total = p["vendors_total"].asLongOrNull()?.toInt() ?: 0
            return when (p["step"].asStringOrNull()) {
                "reading" -> "Reading the posting"
                "research" -> "Researching the company"
                "drafting" -> if (total > 0) "Drafting · $done of $total vendors done" else "Drafting"
                else -> ""
            }
        }

    private fun fitList(key: String): List<String> =
        data["fit_summary"].asObjectOrNull()?.get(key).asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull()?.takeIf(String::isNotBlank) }

    /** The title, else the first line of the captured text, else the link. */
    val displayTitle: String
        get() = title.ifEmpty {
            captureText.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() }?.take(120)
                ?: url.ifEmpty { "Untitled job" }
        }
}
