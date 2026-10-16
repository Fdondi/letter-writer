package io.github.fdondi.letterwriter.core

/** Fields of `personal_data/{sub}/secrets/api_keys` (written by `scripts/firebase/seed_api_keys.py` or Settings). */
data class ApiKeys(val values: Map<String, String>) {
    fun get(field: String): String? = values[field]?.trim()?.takeIf { it.isNotEmpty() }

    fun require(field: String, purpose: String): String =
        get(field) ?: throw MissingApiKeyException(field, purpose)

    fun has(field: String): Boolean = get(field) != null

    companion object {
        const val OPENAI = "openai"
        const val ANTHROPIC = "anthropic"
        const val GEMINI = "gemini"
        const val MISTRAL = "mistral"
        const val XAI = "xai"
        const val DEEPSEEK = "deepseek"
        const val GOOGLE_TRANSLATE = "google_translate"
        const val DECISION_MODEL = "decision_model"

        val ALL = listOf(OPENAI, ANTHROPIC, GEMINI, MISTRAL, XAI, DEEPSEEK, GOOGLE_TRANSLATE, DECISION_MODEL)
    }
}

class MissingApiKeyException(val field: String, purpose: String) :
    IllegalStateException("No '$field' API key saved (needed for $purpose). Add it in Settings → API keys.")
