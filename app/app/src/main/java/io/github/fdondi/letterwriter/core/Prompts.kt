package io.github.fdondi.letterwriter.core

import kotlinx.serialization.json.JsonElement
import java.util.concurrent.ConcurrentHashMap

class MissingPlaceholderException(message: String) : IllegalArgumentException(message)

/** Mirror of `letter_writer/prompts/__init__.py`: verbatim templates, single-pass fill. */
class Prompts(private val assets: SharedAssets) {
    private val cache = ConcurrentHashMap<String, String>()

    fun load(name: String): String = cache.getOrPut(name) { assets.prompt(name) }

    fun loadJson(name: String): JsonElement = Json.parse(load(name))

    fun render(name: String, vararg values: Pair<String, String>): String =
        fill(load(name), name, values.toMap())

    companion object {
        private val PLACEHOLDER = Regex("""\{\{([a-z_][a-z0-9_]*)\}\}""")

        fun fill(text: String, label: String, values: Map<String, String>): String {
            val missing = PLACEHOLDER.findAll(text).map { it.groupValues[1] }.toSortedSet() - values.keys
            if (missing.isNotEmpty()) {
                throw MissingPlaceholderException("Prompt $label needs values for: ${missing.joinToString(", ")}")
            }
            return PLACEHOLDER.replace(text) { m -> values.getValue(m.groupValues[1]) }
        }

        fun fill(text: String, label: String, vararg values: Pair<String, String>): String =
            fill(text, label, values.toMap())
    }
}
