package io.github.fdondi.letterwriter.debug

import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.llm.RoleRef
import kotlinx.serialization.json.JsonObject

/**
 * Stands in for a vendor client while the debug harness is on.
 * Every reply is a file under `app/debug/fixtures`. An unrecognized call throws
 * instead of returning something that could be mistaken for a model reply.
 */
class FakeLlmClient(
    override val vendor: ModelVendor,
    private val fixtures: DebugFixtures,
) : LlmClient {
    override suspend fun call(
        role: RoleRef,
        system: String,
        userMessages: List<String>,
        search: Boolean,
        responseFormat: JsonObject?,
        cachePrefix: String?,
        systemCachePrefix: String?,
        promptCacheKey: String?,
    ): String = fixtures.text(fixtureName(role, system, userMessages, search))

    companion object {
        /** Which fixture file answers this call. Visible so tests can lock the mapping. */
        fun fixtureName(role: RoleRef, system: String, userMessages: List<String>, search: Boolean): String {
            val user = userMessages.joinToString("\n")
            return when (role) {
                is RoleRef.Role -> when (role.role) {
                    ModelRole.LETTER_PLAN -> "letter_plan.txt"
                    ModelRole.LETTER_DRAFT -> "letter_draft.json"
                    ModelRole.LETTER_REFINE -> if ("more fancy style" in user) "letter_fancy.txt" else "letter_rewrite.txt"
                    ModelRole.EXTRACTION -> when {
                        "point_of_contact" in user -> "extraction_metadata.json"
                        "hire_problem" in user -> "extraction_competences.json"
                        user.startsWith("Key competences") -> "extraction_grade.json"
                        else -> refuse("extraction", user)
                    }
                    ModelRole.RAG_RANKER ->
                        throw IllegalStateException(
                            "Debug harness does not rank similar letters, because that search calls a model. Paid APIs were not called.",
                        )
                    ModelRole.FEEDBACK -> feedbackFixture(system)
                    ModelRole.FEEDBACK_REVIEW -> reviewFixture(user)
                    ModelRole.FEEDBACK_CONTEXT -> "feedback_context.json"
                    ModelRole.TRANSLATION -> "translation.txt"
                    ModelRole.COMPANY_RESEARCH -> "company_report.txt"
                }
                is RoleRef.ModelId -> when {
                    search -> "web_search.txt"
                    user.startsWith("Research the following person") -> "poc_report.txt"
                    user.startsWith("Search the internet and write a short") -> "company_report.txt"
                    else -> refuse("model '${role.id}'", user)
                }
            }
        }

        private fun feedbackFixture(system: String): String = when {
            "consistency with the style instructions" in system -> "feedback_instruction.json"
            "factual accuracy against the user's CV" in system -> "feedback_accuracy.json"
            "addresses the needs of the company" in system -> "feedback_precision.json"
            "company's values, mission, tone" in system -> "feedback_empty.json"
            "senior hiring manager" in system -> "feedback_empty.json"
            "continuity of voice" in system -> "feedback_empty.json"
            "patterns behind edits" in system -> "feedback_empty.json"
            else -> refuse("feedback", system)
        }

        private fun reviewFixture(user: String): String = when {
            user.startsWith("Critiques:") -> "review_stage12.json"
            user.startsWith("Items:") -> "review_stage3.json"
            user.startsWith("Rows:") -> "review_stage4.json"
            else -> refuse("feedback review", user)
        }

        private fun refuse(what: String, prompt: String): String {
            throw IllegalStateException(
                "Debug harness has no fixture for this $what call. Paid APIs were not called. Prompt starts: ${prompt.take(160)}",
            )
        }
    }
}
