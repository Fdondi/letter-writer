package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.PromptCache
import io.github.fdondi.letterwriter.llm.call
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Prompts for one checker: system, user prompt, and the cached context block. */
data class CheckerPrompt(val system: String, val prompt: String, val context: String)

/** One category's outcome. [error] is set when every attempt failed (the desktop silently returns no items). */
data class CheckResult(val items: List<JsonObject>, val error: String?)

/** Port of the phased checks in `feedback_checks.py`. */
class FeedbackChecks(private val prompts: Prompts, private val defaultStyle: () -> String) {

    /** `get_phased_feedback_checker_prompts` plus the matching `_*_context` block. Null for `human` without revision examples. */
    fun checker(category: String, letter: String, inputs: LetterInputs): CheckerPrompt? {
        val si = inputs.styleInstructions.ifEmpty { defaultStyle() }
        return when (category) {
            "instruction" -> CheckerPrompt(
                prompts.load("feedback/instruction_system.txt"),
                prompts.load("feedback/instruction_user.txt"),
                instructionContext(si, letter),
            )
            "accuracy" -> {
                val add = if (inputs.additionalUserInfo.isNotBlank()) prompts.render("feedback/accuracy_additional_info.txt", "info" to inputs.additionalUserInfo) else ""
                CheckerPrompt(
                    prompts.render("feedback/accuracy_system.txt", "additional_context" to add),
                    prompts.load("feedback/accuracy_user.txt"),
                    cvLetterContext(inputs.cvText, letter),
                )
            }
            "precision" -> CheckerPrompt(
                prompts.load("feedback/precision_system.txt"),
                prompts.load("feedback/precision_user.txt"),
                companyJobLetterContext(inputs.companyReport, inputs.jobText, letter),
            )
            "company_fit" -> CheckerPrompt(
                prompts.load("feedback/company_fit_system.txt"),
                prompts.load("feedback/company_fit_user.txt"),
                companyJobLetterContext(inputs.companyReport, inputs.jobText, letter),
            )
            "goal_fit" -> {
                val hp = inputs.hireProblem.trim()
                val framing = prompts.load(if (hp.isNotEmpty()) "feedback/goal_fit_framing_with_hire.txt" else "feedback/goal_fit_framing_inferred.txt")
                CheckerPrompt(
                    prompts.render("feedback/goal_fit_system.txt", "framing" to framing),
                    prompts.load("feedback/goal_fit_user.txt"),
                    goalContext(inputs.companyReport, inputs.jobText, letter, hp),
                )
            }
            "user_fit" -> {
                var examples = inputs.topDocs.withIndex()
                    .filter { (_, ex) -> FeedbackItems.pyBool(ex["letter_text"]) }
                    .joinToString("\n\n") { (i, ex) ->
                        "---- Example #${i + 1} - ${ex["company_name"].pyStr()} ----\nCover Letter:\n${ex["letter_text"].pyStr()}\n\n"
                    }
                if (examples.isBlank()) examples = "(No reference letters available.)"
                val add = inputs.additionalUserInfo.trim().let { if (it.isNotEmpty()) prompts.render("feedback/user_fit_additional_info.txt", "info" to it) else "" }
                CheckerPrompt(
                    prompts.load("feedback/user_fit_system.txt"),
                    prompts.render("feedback/user_fit_user.txt", "examples" to examples, "additional_block" to add),
                    cvLetterContext(inputs.cvText, letter),
                )
            }
            "human" -> {
                val examples = humanExamples(inputs.topDocs) ?: return null
                CheckerPrompt(
                    prompts.load("feedback/human_system.txt"),
                    prompts.load("feedback/human_user.txt"),
                    "========== Reference Examples:\n$examples\n==========\n========== Cover Letter to Check:\n$letter\n==========",
                )
            }
            else -> throw IllegalArgumentException("Unknown feedback category: '$category'")
        }
    }

    /** `run_phased_feedback_checks` minus quote spans and decision scoring (the caller does those). */
    suspend fun runAll(letter: String, inputs: LetterInputs, knownWeaknesses: JsonArray, client: LlmClient): LinkedHashMap<String, CheckResult> {
        val tasks = FeedbackItems.CATEGORIES.map { cat ->
            val checker = checker(cat, letter, inputs)
            val prefix = checker?.context ?: humanFallbackContext(letter)
            Triple<String, String?, suspend () -> CheckResult>(cat, prefix) {
                if (checker == null) CheckResult(emptyList(), null) else callItems(cat, checker, inputs.topDocs, knownWeaknesses, client)
            }
        }
        val results = PromptCache.runCacheGroupedTasks(tasks, maxParallelGroups = 7)
        val out = LinkedHashMap<String, CheckResult>()
        for (cat in FeedbackItems.CATEGORIES) out[cat] = results[cat] ?: CheckResult(emptyList(), null)
        return out
    }

    /** `_call_vendor_feedback_items`. */
    internal suspend fun callItems(
        category: String,
        checker: CheckerPrompt,
        topDocs: List<JsonObject>,
        knownWeaknesses: JsonArray,
        client: LlmClient,
        maxRetries: Int = 2,
    ): CheckResult {
        val allowed = FeedbackItems.materialAllowed(FeedbackItems.allowedSources(category, topDocs))
        val legacy = FeedbackItems.legacySource(category, topDocs)
        val schema = schemaWithSources("schemas/vendor_feedback.json", allowed, CONTEXT_SOURCE_PATH)
        val common = prompts.render("feedback/common_instructions.txt", "allowed_sources" to allowed.sorted().joinToString(", "))
        val kwBlock = knownWeaknessesBlock(knownWeaknesses)
        val kwRules = if (kwBlock.isNotEmpty()) prompts.load("feedback/known_weaknesses_rules.txt") else ""
        val system = checker.system + common + kwRules
        val prompt = checker.prompt + kwBlock
        val cacheKey = PromptCache.cacheKeyForPrefix(checker.context, "").ifEmpty { null }
        var lastError = ""
        for (attempt in 1..maxRetries) {
            try {
                val raw = client.call(
                    ModelRole.FEEDBACK,
                    system,
                    listOf(prompt),
                    responseFormat = schema,
                    systemCachePrefix = checker.context,
                    promptCacheKey = cacheKey,
                )
                return CheckResult(FeedbackItems.normalizeParsed(ModelOutput.extractJsonValue(raw), allowed, legacy), null)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                lastError = "attempt $attempt/$maxRetries: ${e.message ?: e::class.simpleName}"
            }
        }
        return CheckResult(emptyList(), "The $category check returned no usable feedback ($lastError)")
    }

    /**
     * `_run_suggest_additional_feedback_context`. The desktop sends this without the
     * checker's context block, so the model never sees the letter or CV it is asked
     * to quote; the phone passes the same block the original check used.
     */
    suspend fun suggestContext(
        category: String,
        observation: String,
        existingContext: List<JsonElement>,
        letter: String,
        inputs: LetterInputs,
        client: LlmClient,
    ): List<JsonObject> {
        val topDocs = if (category == "user_fit" || category == "human") inputs.topDocs else null
        val checker = checker(category, letter, inputs)
            ?: throw IllegalArgumentException("The human-dimension checker has no reference materials (no AI letter examples with revision history).")
        val allowed = FeedbackItems.allowedSources(category, topDocs)
        val legacy = FeedbackItems.legacySource(category, topDocs)
        val existing = existingContext.mapNotNull { raw ->
            val t = if (raw is JsonObject) raw.textOrEmpty("text").trim() else raw.pyStr().trim()
            t.ifEmpty { null }
        }
        val existingBlock = if (existing.isNotEmpty()) existing.joinToString("\n") { "- $it" } else "(none)"
        val task = prompts.render(
            "feedback/suggest_context_task.txt",
            "observation" to observation.trim(),
            "existing_block" to existingBlock,
            "allowed_sources" to allowed.sorted().joinToString(", "),
        )
        val schema = schemaWithSources("schemas/missing_context_items.json", allowed, MISSING_SOURCE_PATH)
        val raw = client.call(
            ModelRole.FEEDBACK_CONTEXT,
            checker.system,
            listOf(checker.prompt + task),
            responseFormat = schema,
            systemCachePrefix = checker.context,
        )
        return FeedbackItems.normalizeMissingContext(ModelOutput.extractJsonValue(raw), allowed, legacy)
    }

    /** `format_known_weaknesses_block`. */
    fun knownWeaknessesBlock(known: JsonArray): String {
        val lines = ArrayList<String>()
        known.forEachIndexed { idx, el ->
            val w = el as? JsonObject ?: return@forEachIndexed
            val i = idx + 1
            val req = w.getStr("requirement").trim()
            val gap = w.getStr("gap").trim()
            when {
                req.isNotEmpty() && gap.isNotEmpty() -> lines += "$i. Requirement: $req | Applicant gap: $gap"
                req.isNotEmpty() -> lines += "$i. $req"
                gap.isNotEmpty() -> lines += "$i. $gap"
            }
        }
        if (lines.isEmpty()) return ""
        return prompts.render("feedback/known_weaknesses_block.txt", "lines" to lines.joinToString("\n"))
    }

    private fun schemaWithSources(file: String, allowed: Set<String>, path: List<Any>): JsonObject {
        val enum = (allowed intersect FeedbackItems.ALL_SOURCES).sorted().ifEmpty { FeedbackItems.MATERIAL_SOURCES.sorted() }
        return replaceAt(prompts.loadJson(file), path, JsonArray(enum.map(::JsonPrimitive))) as JsonObject
    }

    private fun humanFallbackContext(letter: String) =
        "========== Reference Examples:\n(No reference examples.)\n==========\n========== Cover Letter to Check:\n$letter\n=========="

    companion object {
        private val CONTEXT_SOURCE_PATH: List<Any> = listOf(
            "json_schema", "schema", "properties", "items", "items", "properties", "context_field",
            "properties", "items", "items", "anyOf", 1, "properties", "source", "enum",
        )
        private val MISSING_SOURCE_PATH: List<Any> = listOf(
            "json_schema", "schema", "properties", "items", "items", "properties", "source", "enum",
        )

        fun instructionContext(style: String, letter: String) =
            "========== Style Instructions:\n$style\n==========\n\n========== Cover Letter to Check:\n$letter\n=========="

        fun cvLetterContext(cv: String, letter: String): String {
            val cvBlock = cv.trim().ifEmpty { "(No CV text was provided in this session.)" }
            return "========== User CV:\n$cvBlock\n==========\n========== Cover Letter to Check:\n$letter\n=========="
        }

        fun companyJobLetterContext(report: String, job: String, letter: String) =
            "========== Company Report:\n$report\n==========\n========== Job Offer:\n$job\n==========\n" +
                "========== Cover Letter to Check:\n$letter\n=========="

        fun goalContext(report: String, job: String, letter: String, hireProblem: String): String {
            val hp = hireProblem.trim()
            val prefix = if (hp.isNotEmpty()) "========== Hire goal / problem this role solves (structured extraction from the posting):\n$hp\n==========\n" else ""
            return prefix + companyJobLetterContext(report, job, letter)
        }

        /** `_format_human_check_examples`. */
        fun humanExamples(topDocs: List<JsonObject>): String? {
            val rewritten = topDocs.filter { ex -> FeedbackItems.pyBool(ex["letter_text"]) && (ex["ai_letters"] as? JsonArray)?.isNotEmpty() == true }
            if (rewritten.isEmpty()) return null
            return rewritten.withIndex().joinToString("\n\n") { (i, ex) ->
                val attempts = (ex["ai_letters"] as JsonArray).withIndex()
                    .filter { (_, al) -> al is JsonObject && FeedbackItems.pyBool(al["text"]) }
                    .joinToString("\n\n") { (j, alEl) ->
                        val al = alEl as JsonObject
                        val sb = StringBuilder("[attempt ${j + 1}]:\n")
                        if (FeedbackItems.pyBool(al["rating"])) sb.append("(Rating: ${al["rating"].pyStr()}/5)\n")
                        if (al["chunks_used"] != null && al["chunks_used"] !is kotlinx.serialization.json.JsonNull) sb.append("(Used chunks: ${al["chunks_used"].pyStr()})\n")
                        if (FeedbackItems.pyBool(al["comment"])) sb.append("(Feedback: \"${al["comment"].pyStr()}\")\n")
                        sb.append(al["text"]?.pyStr() ?: "")
                        if (FeedbackItems.pyBool(al["user_corrections"])) {
                            val corrections = (al["user_corrections"] as? JsonArray).orEmpty().filterIsInstance<JsonObject>().filter { c ->
                                val type = c["type"]?.pyStr()
                                val hasOrig = c["original"] != null && c["original"] !is kotlinx.serialization.json.JsonNull
                                val hasEdit = c["edited"] != null && c["edited"] !is kotlinx.serialization.json.JsonNull
                                (type == "full" && hasOrig && hasEdit) || (type == "diff" && (hasOrig || hasEdit))
                            }
                            sb.append("\n\nUser corrections made to this letter:\n" + corrections.joinToString("\n") { formatCorrection(it) })
                        }
                        sb.toString()
                    }
                "---- Example #${i + 1} - ${ex["company_name"].pyStr()} ----\nInitial cover letters:\n" + attempts +
                    "\n\nRevised cover Letter:\n${ex["letter_text"].pyStr()}\n\n"
            }
        }

        /** `_format_correction`. */
        private fun formatCorrection(c: JsonObject): String {
            val type = c["type"]?.pyStr() ?: "full"
            val original = (c["original"]?.pyStr() ?: "").trim()
            val edited = (c["edited"]?.pyStr() ?: "").trim()
            if (type == "diff") return if (original.isNotEmpty() || edited.isNotEmpty()) "  -$original+$edited" else "  (empty correction)"
            return "  Original: $original\n  Edited: $edited"
        }

        /** Copy of [root] with the value at [path] (object keys or array indexes) replaced. */
        fun replaceAt(root: JsonElement, path: List<Any>, value: JsonElement): JsonElement {
            if (path.isEmpty()) return value
            val head = path.first()
            val rest = path.drop(1)
            return when (head) {
                is String -> {
                    val o = root as? JsonObject ?: throw IllegalStateException("Schema path expects an object at '$head'")
                    val child = if (rest.isEmpty()) value else replaceAt(o[head] ?: throw IllegalStateException("Schema path missing '$head'"), rest, value)
                    JsonObject(o.toMutableMap().apply { put(head, child) })
                }
                is Int -> {
                    val a = root as? JsonArray ?: throw IllegalStateException("Schema path expects an array at [$head]")
                    JsonArray(a.toMutableList().apply { set(head, replaceAt(a[head], rest, value)) })
                }
                else -> throw IllegalArgumentException("Bad path element $head")
            }
        }
    }
}
