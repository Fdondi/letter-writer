package io.github.fdondi.letterwriter.data

import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.pyStr
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

data class LanguageEntry(
    val code: String,
    val label: String,
    val color: String?,
    val enabled: Boolean,
    val level: String,
    val instructions: String,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("code", code)
        put("label", label)
        put("color", color?.let { JsonPrimitive(it) } ?: JsonNull)
        put("enabled", enabled)
        put("level", level)
        put("instructions", instructions)
    }
}

/** Port of `letter_writer/language_settings.py`, driven by `prompts/language/settings.json`. */
class LanguageSettings(private val prompts: Prompts) {
    private val settings = prompts.loadJson("language/settings.json") as JsonObject
    private val lines = settings["lines"] as JsonObject
    val cefrLevels: List<String> = settings["cefr_levels"].asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull() }
    private val guidance = settings["level_guidance"].asObjectOrNull().orEmpty().mapValues { it.value.pyStr() }
    private val defaultLevelByCode = settings["default_level_by_code"].asObjectOrNull().orEmpty().mapValues { it.value.pyStr() }
    private val fallbackLevel = settings["fallback_level"].pyStr()
    private val defaultInstructionsByCode =
        settings["default_instructions_by_code"].asObjectOrNull().orEmpty().mapValues { it.value.pyStr() }
    private val codeAliases: List<Pair<String, String>> = settings["code_aliases"].asArrayOrNull().orEmpty().map {
        val pair = it as JsonArray
        pair[0].pyStr() to pair[1].pyStr()
    }
    private val aliasMap = LinkedHashMap<String, String>().apply { codeAliases.forEach { (a, c) -> put(a, c) } }

    private fun line(key: String): String = lines[key].pyStr()

    fun normalizeLevel(raw: String?): String {
        val level = raw?.trim().orEmpty()
        if (level.isEmpty()) return ""
        if (level.lowercase() == "native") return "native"
        val upper = level.uppercase()
        return if (upper in cefrLevels) upper else ""
    }

    fun defaultLevelForCode(code: String): String = defaultLevelByCode[code.trim().lowercase()] ?: fallbackLevel

    fun normalizeEntry(raw: JsonElement?): LanguageEntry? {
        val o = raw as? JsonObject ?: return null
        val code = o["code"].textOrBlank().trim().lowercase()
        if (code.isEmpty()) return null
        val level = normalizeLevel(o["level"].textOrBlank()).ifEmpty { defaultLevelForCode(code) }
        var instructions = o["instructions"].textOrBlank()
        if (instructions.isBlank() && code in defaultInstructionsByCode) instructions = defaultInstructionsByCode.getValue(code)
        val labelRaw = o["label"].textOrBlank()
        return LanguageEntry(
            code = code,
            label = labelRaw.ifEmpty { code.uppercase() },
            color = o["color"].asStringOrNull(),
            enabled = o["enabled"]?.asBooleanOrNull() != false,
            level = level,
            instructions = instructions,
        )
    }

    fun normalizeDefaultLanguages(raw: JsonElement?): List<LanguageEntry> =
        (raw as? JsonArray).orEmpty().mapNotNull { normalizeEntry(it) }

    fun defaultLanguages(profile: JsonObject): List<LanguageEntry> =
        normalizeDefaultLanguages(profile["default_languages"]).ifEmpty { normalizeDefaultLanguages(settings["default_languages"]) }

    fun resolveLanguageCode(languageHint: String, profile: JsonObject?): String {
        val hint = languageHint.trim().lowercase()
        if (hint.isEmpty()) return ""
        aliasMap[hint]?.let { return it }
        if (profile != null) {
            for (entry in defaultLanguages(profile)) {
                if (hint == entry.code.lowercase() || hint == entry.label.lowercase()) return entry.code.lowercase()
            }
        }
        for ((alias, code) in aliasMap) {
            if (alias in hint || hint in alias) return code
        }
        return if (hint.length >= 2) hint.substring(0, 2) else hint
    }

    fun resolveEntry(
        profile: JsonObject,
        languageHint: String,
        levelOverride: String? = null,
        instructionsOverride: String? = null,
    ): LanguageEntry? {
        val code = resolveLanguageCode(languageHint, profile)
        if (code.isEmpty()) return null
        var entry = defaultLanguages(profile).firstOrNull { it.code == code }
            ?: normalizeEntry(buildJsonObject { put("code", code) })
            ?: return null
        if (!levelOverride.isNullOrEmpty()) {
            normalizeLevel(levelOverride).takeIf { it.isNotEmpty() }?.let { entry = entry.copy(level = it) }
        }
        if (instructionsOverride != null) entry = entry.copy(instructions = instructionsOverride)
        return entry
    }

    private fun levelPhrase(level: String): String =
        if (level == "native") line("level_native") else Prompts.fill(line("level_cefr"), "language.level_cefr", "level" to level)

    fun instructionLines(entry: LanguageEntry, forTranslation: Boolean): List<String> {
        val name = entry.label.trim().ifEmpty { entry.code.trim().uppercase() }
        val level = normalizeLevel(entry.level).ifEmpty { defaultLevelForCode(entry.code) }
        val key = if (forTranslation) "translate" else "write"
        val out = ArrayList<String>()
        out.add(Prompts.fill(line(key), "language.$key", "name" to name, "level_phrase" to levelPhrase(level)))
        guidance[level]?.takeIf { it.isNotEmpty() }?.let { out.add(it) }
        val capped = lines["capped_levels"].asArrayOrNull().orEmpty().map { it.pyStr() }
        if (level in capped) out.add(line("level_cap"))
        entry.instructions.trim().takeIf { it.isNotEmpty() }?.let { out.add(it) }
        return out
    }

    /** Block prepended to letter-generation system prompts (Python `build_language_system_prefix`). */
    fun systemPrefix(
        profile: JsonObject,
        languageHint: String,
        levelOverride: String? = null,
        instructionsOverride: String? = null,
    ): String {
        val entry = resolveEntry(profile, languageHint, levelOverride, instructionsOverride) ?: return ""
        val body = instructionLines(entry, forTranslation = false)
        if (body.isEmpty()) return ""
        return Prompts.fill(line("prefix"), "language.prefix", "body" to body.joinToString("\n"))
    }

    fun translationSystemMessage(
        profile: JsonObject,
        targetLanguage: String,
        sourceLanguage: String? = null,
        levelOverride: String? = null,
        instructionsOverride: String? = null,
    ): String {
        val entry = resolveEntry(profile, targetLanguage, levelOverride, instructionsOverride)
            ?: LanguageEntry(targetLanguage, targetLanguage.uppercase(), null, true, fallbackLevel, "")
        val parts = ArrayList<String>()
        parts.add(line("translator_intro"))
        parts.addAll(instructionLines(entry, forTranslation = true))
        parts.add(line("preserve_formatting"))
        parts.add(line("output_only"))
        val src = sourceLanguage?.trim().orEmpty()
        if (src.isNotEmpty()) parts.add(1, Prompts.fill(line("source_language"), "language.source_language", "code" to src))
        return parts.joinToString("\n")
    }

    fun translationProvider(profile: JsonObject): String {
        var raw = profile["translation_provider"]
        if (raw is JsonObject && "value" in raw) raw = raw["value"]
        val provider = (if (raw.isNullOrFalsy()) "google" else raw.pyStr()).trim().lowercase()
        return if (provider == "llm" || provider == "google") provider else "google"
    }

    private fun JsonElement?.textOrBlank(): String = if (isNullOrFalsy()) "" else pyStr()

    private fun JsonElement?.isNullOrFalsy(): Boolean =
        this == null || this is JsonNull || (this is JsonPrimitive && isString && content.isEmpty())
}

private fun JsonObject?.orEmpty(): JsonObject = this ?: JsonObject(emptyMap())
