package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.core.Http
import io.github.fdondi.letterwriter.core.Json
import io.github.fdondi.letterwriter.core.PyText
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.data.LanguageSettings
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelRole
import io.github.fdondi.letterwriter.llm.call
import kotlinx.serialization.json.JsonObject
import okhttp3.FormBody
import okhttp3.Request

data class Translation(val text: String, val provider: String, val levelApplied: String?, val warning: String?)

/** Port of `/api/translate/` and `translate_with_llm`. Costs are recorded by the caller. */
class Translator(private val languages: LanguageSettings) {

    /** Google Translate v2. [onCharacters] receives the billed character count. */
    suspend fun google(
        text: String,
        target: String,
        source: String?,
        apiKey: String,
        profile: JsonObject,
        levelOverride: String?,
        instructionsOverride: String?,
        onCharacters: suspend (Int) -> Unit,
    ): Translation {
        if (text.isBlank()) return Translation("", "google", null, null)
        val applied = languages.resolveEntry(profile, target, levelOverride, instructionsOverride)?.level
        val form = FormBody.Builder()
            .add("q", text)
            .add("target", target)
            .add("format", "text")
            .add("key", apiKey)
            .apply { if (!source.isNullOrEmpty()) add("source", source) }
            .build()
        val request = Request.Builder().url(GOOGLE_URL).post(form).build()
        val body = Json.parse(Http.execute("Google Translate", request))
        val translated = body.asObjectOrNull()?.get("data").asObjectOrNull()?.get("translations").asArrayOrNull()
            ?.firstOrNull().asObjectOrNull()?.get("translatedText").asStringOrNull()
            ?: throw ModelOutputException("Google Translate reply has no translatedText: ${ModelOutput.preview(body.toString())}")
        onCharacters(PyText.length(text))
        val warning = applied?.takeIf { it.isNotEmpty() }?.let {
            "Google Translate ignores CEFR level ($it). Switch to LLM translation in Settings to honor language level."
        }
        return Translation(translated, "google", null, warning)
    }

    /** `translate_with_llm` (Gemini, role `translation`). */
    suspend fun llm(
        text: String,
        target: String,
        source: String?,
        profile: JsonObject,
        levelOverride: String?,
        instructionsOverride: String?,
        gemini: LlmClient,
    ): Translation {
        if (text.isBlank()) return Translation("", "llm", null, null)
        val applied = languages.resolveEntry(profile, target, levelOverride, instructionsOverride)?.level
        val system = languages.translationSystemMessage(profile, target, source, levelOverride, instructionsOverride)
        val out = gemini.call(ModelRole.TRANSLATION, system, listOf(text)).trim()
        return Translation(out, "llm", applied, null)
    }

    companion object {
        private const val GOOGLE_URL = "https://translation.googleapis.com/language/translate/v2"
    }
}
