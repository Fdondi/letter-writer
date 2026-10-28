package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.data.Opportunity
import io.github.fdondi.letterwriter.decision.StoredFieldNames
import io.github.fdondi.letterwriter.llm.ModelVendor
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Turns the desktop session the pipeline stored in `opportunities/{id}/state/session`
 * (the cookie-session dict: `job_text`, `metadata.common`, `selected_top_docs`,
 * `vendors.<vendor>.{letter_plan, draft_letter, final_letter, feedback, known_weaknesses, company_report, cost}`)
 * into the phone's [WorkSession], so the drafts open in the usual Letters and Final tabs.
 */
object PipelineSession {
    /** Desktop vendors the phone has no client for. Their drafts are shown; rewrites use a stand-in vendor. */
    val DESKTOP_ONLY_VENDORS = mapOf(
        // Anthropic as the desktop runs it; on the phone the same vendor is the Anthropic API.
        "claude_code" to "Anthropic (Claude Code)",
        "local" to "Local model",
    )

    /** Which phone vendor rewrites a desktop-only vendor's draft, before the user's other vendors. */
    val STAND_INS = mapOf("claude_code" to listOf(ModelVendor.ANTHROPIC))

    /** Report key in [JobIntake.companyReports] for the desktop's research. */
    const val DESKTOP_REPORT = "desktop"

    fun isPhoneVendor(vendor: String): Boolean = ModelVendor.fromKey(vendor) != null

    fun toWorkSession(opportunity: Opportunity, state: JsonObject): WorkSession {
        val s = StoredFieldNames.fromStored(state) as JsonObject
        val common = s["metadata"].asObjectOrNull()?.get("common").asObjectOrNull() ?: JsonObject(emptyMap())
        fun c(key: String) = common[key].asStringOrNull()?.trim().orEmpty()
        val stored = s["vendors"].asObjectOrNull() ?: JsonObject(emptyMap())

        val order = (opportunity.vendorsDone + stored.keys).distinct()
        val work = LinkedHashMap<String, VendorWork>()
        for (v in order) {
            val d = stored[v].asObjectOrNull() ?: continue
            val draft = d["draft_letter"].asStringOrNull().orEmpty()
            val final = d["final_letter"].asStringOrNull().orEmpty()
            if (draft.isBlank() && final.isBlank()) continue
            val cost = d["cost"].asDoubleOrNull() ?: 0.0
            work[v] = VendorWork(
                vendor = v,
                stage = if (final.isNotBlank()) VendorStage.FINAL else VendorStage.DRAFT,
                letterPlan = d["letter_plan"].asStringOrNull().orEmpty(),
                draftLetter = draft,
                knownWeaknesses = d["known_weaknesses"].asArrayOrNull() ?: JsonArray(emptyList()),
                feedback = d["feedback"].asObjectOrNull() ?: JsonObject(emptyMap()),
                finalLetter = final,
                costs = if (cost > 0) mapOf("desktop" to cost) else emptyMap(),
                // Sessions from before the marker: the desktop commented the draft, then rewrote it.
                commentsOn = d["comments_on"].asStringOrNull() ?: if (d.containsKey("comments_on")) null else "draft_letter",
            )
        }

        val report = order.firstNotNullOfOrNull { v ->
            stored[v].asObjectOrNull()?.get("company_report").asStringOrNull()?.takeIf { it.isNotBlank() }
        }.orEmpty()
        val topDocs = (s["selected_top_docs"].asArrayOrNull()?.takeIf { it.isNotEmpty() }
            ?: order.firstNotNullOfOrNull { v -> stored[v].asObjectOrNull()?.get("top_docs").asArrayOrNull()?.takeIf { it.isNotEmpty() } })
            .orEmpty().mapNotNull { it.asObjectOrNull() }
        val failures = opportunity.vendorsFailed.map { (v, err) -> "${label(v)} could not draft on the desktop: $err" }

        val intake = JobIntake(
            jobText = s["job_text"].asStringOrNull()?.takeIf { it.isNotBlank() } ?: opportunity.captureText,
            companyName = c("company_name").ifEmpty { opportunity.company },
            jobTitle = c("job_title").ifEmpty { opportunity.title },
            location = c("location").ifEmpty { opportunity.location },
            language = c("language"),
            salary = c("salary"),
            sourceUrl = c("source_url").ifEmpty { opportunity.url },
            pointOfContact = common["point_of_contact"].asObjectOrNull()?.takeIf { it.isNotEmpty() },
            hireProblem = c("hire_problem"),
            requirements = common["requirements"].asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull() },
            competences = common["competences"].asObjectOrNull() ?: JsonObject(emptyMap()),
            additionalUserInfo = c("additional_user_info"),
            additionalCompanyInfo = c("additional_company_info"),
            extracted = true,
            similarDocuments = topDocs,
            selectedDocIds = topDocs.map(WorkSession::docKey).filter { it.isNotEmpty() },
            companyReports = if (report.isEmpty()) {
                JsonObject(emptyMap())
            } else {
                JsonObject(mapOf(DESKTOP_REPORT to buildJsonObject { put("report", JsonPrimitive(report)) }))
            },
            researchSource = if (report.isEmpty()) "" else DESKTOP_REPORT,
            selectedReportModel = if (report.isEmpty()) null else DESKTOP_REPORT,
            companyReport = report,
            warnings = failures,
        )
        return WorkSession(
            intake = intake,
            vendors = work.keys.toList(),
            includePlanStep = true,
            work = work,
            documentId = opportunity.documentId,
            opportunityId = opportunity.id,
        )
    }

    /** Open INPUT_NEEDED questions across the session's vendors (what the desktop counts as `input_needed_count`). */
    fun openQuestions(s: WorkSession): Int = s.vendors.sumOf { v ->
        val w = s.vendorWork(v)
        FeedbackItems.CATEGORIES.sumOf { cat ->
            w.items(cat).count { it["status"].asStringOrNull()?.uppercase() == "INPUT_NEEDED" && !FeedbackUi.itemIsApproved(it, w.itemApprovals) && !FeedbackUi.isHidden(it) }
        }
    }

    fun label(vendor: String): String = ModelVendor.fromKey(vendor)?.label ?: DESKTOP_ONLY_VENDORS[vendor] ?: vendor
}
