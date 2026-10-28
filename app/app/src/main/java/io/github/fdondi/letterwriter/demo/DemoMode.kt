package io.github.fdondi.letterwriter.demo

import android.content.Context
import io.github.fdondi.letterwriter.auth.SignedInUser

/**
 * Demo mode: the whole app on a made-up account, in-memory data and canned model replies
 * (`assets/fixtures`), with no sign-in. Nothing leaves the phone. Chosen on the sign-in screen,
 * or from adb for scripted tests:
 *
 *     adb shell am start -n io.github.fdondi.letterwriter/.MainActivity --ez io.github.fdondi.letterwriter.DEMO true
 *
 * The choice survives restarts; leaving demo (sign out, or `--ez …DEMO false`) returns to the
 * real account. Demo work lives in its own folder, so it never replaces a real letter in progress.
 */
object DemoMode {
    const val EXTRA = "io.github.fdondi.letterwriter.DEMO"
    val USER = SignedInUser(sub = "demo-user", email = "demo@example.invalid", displayName = "Demo")

    private const val PREFS = "app_mode"
    private const val KEY = "demo"

    fun isOn(context: Context): Boolean = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY, false)

    fun save(context: Context, on: Boolean) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY, on).apply()
    }
}
