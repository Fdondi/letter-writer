package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.call
import io.github.fdondi.letterwriter.llm.ref
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

class MissingCvException(message: String) : IllegalStateException(message)

/** What every letter phase reads: the job, the user and the picked examples / report. */
data class LetterInputs(
    val cvText: String,
    val jobText: String,
    val companyReport: String,
    val topDocs: List<JsonObject>,
    val additionalUserInfo: String,
    val hireProblem: String,
    val languagePrefix: String,
    val styleInstructions: String,
    val structureInstructions: String,
)

/** Port of `letter_generation.py`, `rewrite.py` and the instruction helpers in `instructions.py`. */
class LetterGeneration(private val prompts: Prompts) {

    fun defaultStyle(): String = prompts.load("defaults/style_instructions.txt")

    fun defaultStructure(): String = prompts.load("defaults/structure_instructions.txt")

    /** `_format_letter_examples`. */
    fun formatExamples(examples: List<JsonObject>): String =
        examples.withIndex()
            .filter { (_, ex) -> ex.textOrEmpty("letter_text").isNotBlank() }
            .joinToString("\n\n") { (i, ex) ->
                prompts.render(
                    "generation/example.txt",
                    "number" to (i + 1).toString(),
                    "score" to (ex["score"]?.pyStr() ?: "0"),
                    "company_name" to (ex["company_name"]?.pyStr() ?: ""),
                    "job_text" to (ex["job_text"]?.pyStr() ?: ""),
                    "letter_text" to (ex["letter_text"]?.pyStr() ?: ""),
                )
            }

    /** `_letter_generation_context`: the cached system block shared by plan and draft. */
    fun generationContext(inputs: LetterInputs): String {
        val hp = inputs.hireProblem.trim()
        val hireBlock = if (hp.isNotEmpty()) prompts.render("generation/context_hire_block.txt", "hire_problem" to hp) else ""
        return prompts.render(
            "generation/context.txt",
            "cv" to inputs.cvText,
            "examples" to formatExamples(inputs.topDocs),
            "company_report" to inputs.companyReport,
            "job" to inputs.jobText,
            "hire_block" to hireBlock,
        )
    }

    /** `generate_letter_plan`. */
    suspend fun plan(inputs: LetterInputs, client: LlmClient): String {
        requireCv(inputs.cvText, "letter plan")
        val si = inputs.structureInstructions.trim().ifEmpty { defaultStructure() }
        val additional = if (inputs.additionalUserInfo.isNotBlank()) prompts.render("generation/plan_additional_info.txt", "info" to inputs.additionalUserInfo) else ""
        val system = prependLanguagePrefix(
            prompts.render("generation/plan_system.txt", "structure_instructions" to si, "additional_context" to additional),
            inputs.languagePrefix,
        )
        return client.call(ModelRole.LETTER_PLAN, system, listOf(prompts.load("generation/plan_user.txt")), systemCachePrefix = generationContext(inputs))
    }

    /** `generate_letter`: returns the letter and the objective known weaknesses. */
    suspend fun draft(inputs: LetterInputs, letterPlan: String, client: LlmClient, maxRetries: Int = 2): Pair<String, JsonArray> {
        requireCv(inputs.cvText, "cover letter")
        val style = inputs.styleInstructions.ifEmpty { defaultStyle() }
        val additional = if (inputs.additionalUserInfo.isNotBlank()) prompts.render("generation/draft_additional_info.txt", "info" to inputs.additionalUserInfo) else ""
        val lp = letterPlan.trim()
        val planBlock = if (lp.isNotEmpty()) prompts.render("generation/draft_plan_block.txt", "plan" to lp) else ""
        val system = prependLanguagePrefix(
            prompts.render("generation/draft_system.txt", "style_instructions" to style, "plan_block" to planBlock, "additional_context" to additional),
            inputs.languagePrefix,
        )
        val context = generationContext(inputs)
        val schema = prompts.loadJson("schemas/draft_letter.json") as JsonObject
        var lastRaw = ""
        var lastError = ""
        for (attempt in 1..maxRetries) {
            try {
                lastRaw = client.call(
                    ModelRole.LETTER_DRAFT,
                    system,
                    listOf(prompts.load("generation/draft_user.txt")),
                    responseFormat = schema,
                    systemCachePrefix = context,
                )
                return parseDraftOutput(ModelOutput.extractJsonValue(lastRaw))
            } catch (e: CancellationException) {
                throw e
            } catch (e: ModelOutputException) {
                lastError = e.message.orEmpty()
            } catch (e: Exception) {
                lastError = e.message ?: e::class.simpleName.orEmpty()
                val l = lastError.lowercase()
                if (PERMANENT_MARKERS.any { it in l }) throw IllegalStateException("Draft letter generation failed: $lastError", e)
            }
        }
        val detail = lastRaw.ifBlank { lastError }.trim()
        throw IllegalStateException("Draft letter generation failed after $maxRetries attempts: ${detail.take(500)}")
    }

    /**
     * `regenerate_paragraph`: rewrite paragraph [index] of [paragraphs] so it fits between the
     * others, addressing [feedback] (see [regenerateFeedback]).
     */
    suspend fun regenerateParagraph(paragraphs: List<String>, index: Int, feedback: String, inputs: LetterInputs, client: LlmClient): String {
        require(index in paragraphs.indices) { "paragraph index $index out of range (0..${paragraphs.size - 1})" }
        val marked = paragraphs.withIndex().joinToString("\n\n") { (i, p) -> if (i == index) ">>>\n$p\n<<<" else p }
        val additional = if (inputs.additionalUserInfo.isNotBlank()) prompts.render("generation/draft_additional_info.txt", "info" to inputs.additionalUserInfo) else ""
        val system = prependLanguagePrefix(
            prompts.render(
                "generation/paragraph_regenerate_system.txt",
                "style_instructions" to inputs.styleInstructions.ifEmpty { defaultStyle() },
                "additional_context" to additional,
            ),
            inputs.languagePrefix,
        )
        val user = prompts.render(
            "generation/paragraph_regenerate_user.txt",
            "letter" to marked,
            "feedback" to feedback.trim().ifEmpty { "(none given: write a stronger alternative)" },
        )
        val text = client.call(ModelRole.PARAGRAPH, system, listOf(user), systemCachePrefix = generationContext(inputs))
        return text.trim().replace(">>>", "").replace("<<<", "").trim()
    }

    /** `fancy_letter`. */
    suspend fun fancy(letter: String, client: LlmClient): String =
        client.call(
            ModelRole.LETTER_REFINE,
            prompts.load("generation/fancy_system.txt"),
            listOf(prompts.load("generation/fancy_user.txt")),
            systemCachePrefix = "========== Cover Letter:\n$letter\n==========\n",
        )

    /** `rewrite_letter`. Returns the original letter when no comment needs fixing or the model answers NO REVISIONS. */
    suspend fun rewrite(
        originalLetter: String,
        feedback: Map<String, JsonArray>,
        client: LlmClient,
        letterPlan: String,
        styleInstructions: String,
        languagePrefix: String,
    ): String {
        val si = styleInstructions.trim().ifEmpty { defaultStyle() }
        val lp = letterPlan.trim()
        val planBlock = if (lp.isNotEmpty()) prompts.render("rewrite/plan_block.txt", "plan" to lp) else ""
        val system = prependLanguagePrefix(prompts.render("rewrite/system.txt", "style_instructions" to si, "plan_block" to planBlock), languagePrefix)
        val parts = StringBuilder("========== Original Cover Letter:\n$originalLetter\n==========\n")
        var hadFeedback = false
        for ((title, key) in REWRITE_DIMENSIONS) {
            val block = dimensionText(feedback[key] ?: JsonArray(emptyList()))
            if (block.isEmpty()) continue
            hadFeedback = true
            parts.append("========== $title:\n$block\n==========\n")
        }
        if (!hadFeedback) return originalLetter
        val revised = client.call(ModelRole.LETTER_REFINE.ref(), system, listOf(prompts.load("rewrite/user.txt")), systemCachePrefix = parts.toString())
        return if ("NO REVISIONS" in revised) originalLetter else revised
    }

    /** `_rewrite_dimension_text` for item lists. */
    private fun dimensionText(items: JsonArray): String {
        val lines = ArrayList<String>()
        for (el in items) {
            val it = el as? JsonObject ?: continue
            if ((it["type"] as? JsonPrimitive)?.content != "PLEASE_FIX") continue
            if (FeedbackItems.isDecisionHidden(it)) continue
            val o = it.textOrEmpty("observation").trim()
            if (o.isEmpty()) continue
            var status = it.textOrEmpty("status").trim().uppercase()
            if (status !in FeedbackItems.STATUSES) status = "NOT_NEEDED"
            val machine = ArrayList<String>()
            val userFromField = ArrayList<String>()
            for (raw in FeedbackItems.contextItems(it)) {
                if (raw is JsonPrimitive && raw.isString) {
                    raw.content.trim().takeIf { t -> t.isNotEmpty() }?.let(machine::add)
                    continue
                }
                val r = raw as? JsonObject ?: continue
                val t = r.textOrEmpty("text").trim()
                val src = r.textOrEmpty("source").trim().uppercase()
                if (t.isEmpty()) continue
                when {
                    src == FeedbackItems.USER_SOURCE -> userFromField += t
                    src in FeedbackItems.MATERIAL_SOURCES -> machine += "[$src] $t"
                    else -> machine += t
                }
            }
            val userContext = (it["user_context"] as? JsonPrimitive)?.takeIf { p -> p.isString }?.content?.trim().orEmpty()
            val declined = status == "INPUT_NEEDED" && FeedbackItems.pyBool(it["input_declined"])
            val extra = ArrayList<String>()
            if (machine.isNotEmpty()) extra += "Available context: " + machine.joinToString("; ")
            val provided = ArrayList<String>()
            if (status == "INPUT_NEEDED" && userContext.isNotEmpty()) provided += userContext
            provided += userFromField
            if (provided.isNotEmpty()) extra += "User-provided context: " + provided.joinToString("; ")
            if (status == "INPUT_NEEDED" && declined && userContext.isEmpty() && userFromField.isEmpty()) {
                extra += prompts.load("rewrite/input_declined_note.txt")
            }
            lines += if (extra.isNotEmpty()) o + "\n  - " + extra.joinToString("\n  - ") else o
        }
        return lines.joinToString("\n")
    }

    companion object {
        private val PERMANENT_MARKERS = listOf(
            "credit balance", "insufficient_quota", "insufficient credits", "invalid_api_key",
            "authentication", "permission denied", "unauthorized",
        )

        private val REWRITE_DIMENSIONS = listOf(
            "Instruction Feedback" to "instruction",
            "Accuracy Feedback" to "accuracy",
            "Precision Feedback" to "precision",
            "Company Fit Feedback" to "company_fit",
            "Goal Fit Feedback" to "goal_fit",
            "User Fit Feedback" to "user_fit",
            "Human Feedback" to "human",
        )

        /** `split_letter_paragraphs`: blank-line separated, like the web's `splitIntoParagraphs`. */
        fun splitParagraphs(text: String): List<String> =
            text.trim().split(Regex("\\n\\s*\\n")).map { it.trim() }.filter { it.isNotEmpty() }

        /**
         * `format_regenerate_feedback`: the user's own text first, then each comment they picked as
         * `- [topic] observation (about: "quote")`.
         */
        fun regenerateFeedback(userFeedback: String, notes: List<JsonObject>): String {
            val parts = ArrayList<String>()
            if (userFeedback.isNotBlank()) parts += userFeedback.trim()
            for (note in notes) {
                val obs = note.textOrEmpty("observation").trim()
                if (obs.isEmpty()) continue
                val topic = note.textOrEmpty("topic").trim()
                val quote = note.textOrEmpty("quote").trim()
                var line = if (topic.isNotEmpty()) "- [$topic] $obs" else "- $obs"
                if (quote.isNotEmpty()) line += " (about: \"$quote\")"
                parts += line
            }
            return parts.joinToString("\n")
        }

        /** `_prepend_language_prefix`. */
        fun prependLanguagePrefix(system: String, languagePrefix: String): String {
            val prefix = languagePrefix.trim()
            if (prefix.isEmpty()) return system
            return prefix + (if (system.isNotEmpty()) "\n\n" else "") + system
        }

        private fun requireCv(cv: String, what: String) {
            if (cv.isBlank()) throw MissingCvException("CV text is missing or empty - cannot generate $what")
        }

        /** `parse_draft_letter_output`. */
        fun parseDraftOutput(data: JsonElement): Pair<String, JsonArray> {
            if (data is JsonPrimitive && data.isString) {
                val text = data.content.trim()
                if (text.isEmpty()) throw ModelOutputException("empty draft_letter")
                return text to JsonArray(emptyList())
            }
            val o = data as? JsonObject ?: throw ModelOutputException("draft output must be a JSON object")
            val letter = o.getStr("draft_letter").trim()
            if (letter.isEmpty()) throw ModelOutputException("missing draft_letter")
            return letter to normalizeKnownWeaknesses(o)
        }

        /** `normalize_known_weaknesses`. */
        fun normalizeKnownWeaknesses(data: JsonElement): JsonArray {
            val raw: List<JsonElement> = when {
                data is JsonObject && data["known_weaknesses"] is JsonArray -> data["known_weaknesses"] as JsonArray
                data is JsonObject && data["weaknesses"] is JsonArray -> data["weaknesses"] as JsonArray
                data is JsonObject && data["items"] is JsonArray -> data["items"] as JsonArray
                data is JsonArray -> data
                else -> emptyList()
            }
            val seen = HashSet<Pair<String, String>>()
            val out = ArrayList<JsonObject>()
            for (el in raw) {
                val it = el as? JsonObject ?: continue
                val req = it.getStr("requirement").trim()
                val gap = it.getStr("gap").trim()
                val desc = it.getStr("description").trim()
                val (key, line) = when {
                    req.isNotEmpty() && gap.isNotEmpty() -> (req.lowercase() to gap.lowercase()) to (req to gap)
                    desc.isNotEmpty() -> (desc.lowercase() to "") to (desc to "")
                    else -> continue
                }
                if (!seen.add(key)) continue
                out += buildJsonObject {
                    put("id", UUID.randomUUID().toString())
                    put("requirement", line.first)
                    put("gap", line.second)
                }
            }
            return JsonArray(out)
        }
    }
}
