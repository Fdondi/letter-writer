package io.github.fdondi.letterwriter.debug

import android.content.res.AssetManager
import java.io.File

/**
 * Reads the labeled replies in `app/debug/fixtures`.
 * A missing file is an error. The harness does not invent a reply in its place.
 */
class DebugFixtures(private val read: (String) -> String) {
    fun text(name: String): String =
        try {
            read(name)
        } catch (e: Exception) {
            throw IllegalStateException("Debug harness fixture '$name' could not be read. Paid APIs were not called.", e)
        }

    companion object {
        fun fromAssets(assets: AssetManager): DebugFixtures = DebugFixtures { name ->
            assets.open("fixtures/$name").use { it.readBytes().toString(Charsets.UTF_8) }
        }

        fun fromDirectory(dir: File): DebugFixtures = DebugFixtures { name ->
            val file = dir.resolve(name)
            if (!file.isFile) throw IllegalStateException("Missing debug fixture $name in ${dir.path}")
            file.readText(Charsets.UTF_8)
        }
    }
}
