package io.github.fdondi.letterwriter.core

import android.content.res.AssetManager
import java.io.File

/**
 * Prompt templates and vendor catalogs shared with the desktop backend.
 *
 * In the app they are copied into assets by the `syncSharedAssets` Gradle task.
 * JVM unit tests read the same files straight from the repository.
 */
interface SharedAssets {
    /** Template text at `letter_writer/prompts/<path>`, exactly as stored. */
    fun prompt(path: String): String

    /** Catalog JSON at `letter_writer/clients/<stem>.json`. Null when the file does not exist. */
    fun catalog(stem: String): String?
}

class AndroidSharedAssets(private val assets: AssetManager) : SharedAssets {
    override fun prompt(path: String): String =
        assets.open("prompts/$path").use { it.readBytes().toString(Charsets.UTF_8) }

    override fun catalog(stem: String): String? =
        try {
            assets.open("catalogs/$stem.json").use { it.readBytes().toString(Charsets.UTF_8) }
        } catch (_: java.io.FileNotFoundException) {
            null
        }
}

class FileSharedAssets(repoRoot: File) : SharedAssets {
    private val promptsDir = repoRoot.resolve("letter_writer/prompts")
    private val clientsDir = repoRoot.resolve("letter_writer/clients")

    override fun prompt(path: String): String = promptsDir.resolve(path).readText(Charsets.UTF_8)

    override fun catalog(stem: String): String? {
        val f = clientsDir.resolve("$stem.json")
        return if (f.isFile) f.readText(Charsets.UTF_8) else null
    }
}
