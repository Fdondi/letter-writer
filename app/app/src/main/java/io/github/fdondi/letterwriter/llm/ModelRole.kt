package io.github.fdondi.letterwriter.llm

/** Named LLM roles; each vendor maps a role to a concrete model in `clients/<vendor>.json`. */
enum class ModelRole(val value: String) {
    EXTRACTION("extraction"),
    FEEDBACK("feedback"),
    FEEDBACK_REVIEW("feedback_review"),
    FEEDBACK_CONTEXT("feedback_context"),
    RAG_RANKER("rag_ranker"),
    COMPANY_RESEARCH("company_research"),
    LETTER_PLAN("letter_plan"),
    LETTER_DRAFT("letter_draft"),
    LETTER_REFINE("letter_refine"),
    TRANSLATION("translation"),
    ;

    companion object {
        fun fromValue(value: String): ModelRole? = entries.firstOrNull { it.value == value }
    }
}

enum class ModelVendor(val key: String, val label: String) {
    OPENAI("openai", "OpenAI"),
    ANTHROPIC("anthropic", "Anthropic"),
    GEMINI("gemini", "Gemini"),
    MISTRAL("mistral", "Mistral"),
    GROK("grok", "Grok"),
    DEEPSEEK("deepseek", "DeepSeek"),
    ;

    /** File stem of the catalog in `letter_writer/clients/` (one is misspelled on disk). */
    val catalogStem: String
        get() = if (this == DEEPSEEK) "deepseeek" else key

    companion object {
        fun fromKey(key: String): ModelVendor? = entries.firstOrNull { it.key == key.trim().lowercase() }
    }
}

/** What `client.call(model_role, ...)` receives: a role, or an explicit `model@suffix` override. */
sealed interface RoleRef {
    /** The string the golden fixtures record for this call. */
    val recorded: String

    data class Role(val role: ModelRole) : RoleRef {
        override val recorded: String get() = role.value
    }

    data class ModelId(val id: String) : RoleRef {
        override val recorded: String get() = id
    }
}

fun ModelRole.ref(): RoleRef = RoleRef.Role(this)
