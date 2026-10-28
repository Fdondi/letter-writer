package io.github.fdondi.letterwriter.core

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import androidx.annotation.RequiresApi
import io.github.fdondi.letterwriter.BuildConfig
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.time.Instant

/**
 * Keeps the last crash on the phone so the app can show it on the next start, without USB debugging.
 * Our own handler records the full stack trace; Android's exit records (API 30+) add crashes we
 * could not catch (native, ANR) and why the process was last stopped.
 */
object CrashLog {
    data class Report(val summary: String, val details: String)

    private fun dir(context: Context) = context.filesDir.resolve("crash")

    private fun reportFile(context: Context) = dir(context).resolve("last_crash.txt")

    /** Exit records at or before this time were already shown. */
    private fun ackFile(context: Context) = dir(context).resolve("acknowledged_exit_ms")

    fun install(context: Context) {
        val file = reportFile(context)
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching {
                file.parentFile?.mkdirs()
                file.writeText(header("crashed on thread '${thread.name}'") + "\n\n" + stackTrace(error))
            }
            // Android still shows its dialog and ends the process.
            previous?.uncaughtException(thread, error)
        }
    }

    /** The last unacknowledged crash: our stack trace, else Android's record of a crash or ANR. */
    fun lastReport(context: Context): Report? {
        val file = reportFile(context)
        if (file.isFile) {
            val text = runCatching { file.readText() }.getOrNull()
            if (!text.isNullOrBlank()) {
                val firstError = text.lineSequence().drop(1).firstOrNull { it.isNotBlank() }?.trim().orEmpty()
                return Report("Letter Writer crashed last time: $firstError", text)
            }
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        val exit = unacknowledgedExit(context) ?: return null
        if (exit.reason !in CRASH_REASONS) return null
        val trace = if (exit.reason == ApplicationExitInfo.REASON_ANR) anrTrace(exit) else ""
        val details = header("stopped: ${describe(exit)}") + (if (trace.isNotEmpty()) "\n\n$trace" else "")
        return Report("Letter Writer stopped last time: ${reasonName(exit.reason)}", details)
    }

    /** Why the previous process ended, when that was not the user or a normal exit; for "interrupted" messages. */
    fun lastStopReason(context: Context): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        val exit = unacknowledgedExit(context) ?: return null
        return if (exit.reason in BENIGN_REASONS) null else describe(exit)
    }

    fun dismiss(context: Context) {
        runCatching { reportFile(context).delete() }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        val newest = latestExit(context)?.timestamp ?: return
        runCatching {
            ackFile(context).parentFile?.mkdirs()
            ackFile(context).writeText(newest.toString())
        }
    }

    @RequiresApi(Build.VERSION_CODES.R)
    private fun latestExit(context: Context): ApplicationExitInfo? {
        val am = context.getSystemService(ActivityManager::class.java) ?: return null
        return runCatching { am.getHistoricalProcessExitReasons(context.packageName, 0, 1).firstOrNull() }.getOrNull()
    }

    @RequiresApi(Build.VERSION_CODES.R)
    private fun unacknowledgedExit(context: Context): ApplicationExitInfo? {
        val exit = latestExit(context) ?: return null
        val acked = runCatching { ackFile(context).readText().trim().toLong() }.getOrDefault(0L)
        return if (exit.timestamp > acked) exit else null
    }

    private fun header(what: String): String =
        "Letter Writer ${BuildConfig.VERSION_NAME} $what at ${Instant.now()}\n" +
            "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}), ${Build.MANUFACTURER} ${Build.MODEL}"

    fun stackTrace(error: Throwable): String = StringWriter().also { error.printStackTrace(PrintWriter(it)) }.toString()

    private val CRASH_REASONS = setOf(
        ApplicationExitInfo.REASON_CRASH,
        ApplicationExitInfo.REASON_CRASH_NATIVE,
        ApplicationExitInfo.REASON_ANR,
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE,
    )

    private val BENIGN_REASONS = setOf(
        ApplicationExitInfo.REASON_EXIT_SELF,
        ApplicationExitInfo.REASON_USER_REQUESTED,
        ApplicationExitInfo.REASON_USER_STOPPED,
        ApplicationExitInfo.REASON_PACKAGE_UPDATED,
        ApplicationExitInfo.REASON_PACKAGE_STATE_CHANGE,
        ApplicationExitInfo.REASON_PERMISSION_CHANGE,
    )

    @RequiresApi(Build.VERSION_CODES.R)
    private fun describe(exit: ApplicationExitInfo): String {
        val at = Instant.ofEpochMilli(exit.timestamp)
        val detail = exit.description?.takeIf { it.isNotBlank() }?.let { " ($it)" }.orEmpty()
        val where = if (exit.importance >= ActivityManager.RunningAppProcessInfo.IMPORTANCE_CACHED) ", in the background" else ""
        return "${reasonName(exit.reason)}$detail$where, at $at"
    }

    private fun reasonName(reason: Int): String = when (reason) {
        ApplicationExitInfo.REASON_CRASH -> "crash"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "native crash"
        ApplicationExitInfo.REASON_ANR -> "not responding (ANR)"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "Android stopped it to free memory"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "Android stopped it for using too many resources"
        ApplicationExitInfo.REASON_FREEZER -> "Android stopped it while it was frozen in the background"
        ApplicationExitInfo.REASON_SIGNALED -> "killed by a signal"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "failed to start"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "a process it depends on died"
        ApplicationExitInfo.REASON_OTHER -> "stopped by Android"
        else -> "exit reason $reason"
    }

    @RequiresApi(Build.VERSION_CODES.R)
    private fun anrTrace(exit: ApplicationExitInfo): String =
        runCatching { exit.traceInputStream?.bufferedReader()?.useLines { it.take(80).joinToString("\n") } }.getOrNull().orEmpty()

    /** Test hook: what [install] would write for [error]. */
    internal fun writeForTest(context: Context, error: Throwable) {
        val file = reportFile(context)
        file.parentFile?.mkdirs()
        file.writeText(header("crashed on thread 'test'") + "\n\n" + stackTrace(error))
    }

    internal fun reportFileForTest(context: Context): File = reportFile(context)
}
