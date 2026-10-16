package io.github.fdondi.letterwriter.core

import android.content.Context
import androidx.datastore.preferences.core.doublePreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.deviceSettingsStore by preferencesDataStore(name = "device_settings")

/**
 * Decision model endpoint settings. They are phone-only (the desktop runs its own
 * local server), so they live on the device rather than in the shared profile.
 *
 * [feedbackHideBelow] is null until the user calibrates it: Jev's `noul` answers
 * carry no confidence, so the desktop's two-threshold rule cannot be reused.
 */
data class DecisionModelSettings(
    val baseUrl: String = DEFAULT_BASE_URL,
    val model: String = DEFAULT_MODEL,
    val feedbackHideBelow: Double? = null,
) {
    companion object {
        const val DEFAULT_BASE_URL = "https://api.typesafe.ai"
        const val DEFAULT_MODEL = "jev-1.13.0"
    }
}

class DeviceSettings(private val context: Context) {
    private val baseUrlKey = stringPreferencesKey("decision_model_base_url")
    private val modelKey = stringPreferencesKey("decision_model_model")
    private val hideBelowKey = doublePreferencesKey("decision_model_feedback_hide_below")

    val decisionModel: Flow<DecisionModelSettings> = context.deviceSettingsStore.data.map { p ->
        DecisionModelSettings(
            baseUrl = p[baseUrlKey]?.takeIf { it.isNotBlank() } ?: DecisionModelSettings.DEFAULT_BASE_URL,
            model = p[modelKey]?.takeIf { it.isNotBlank() } ?: DecisionModelSettings.DEFAULT_MODEL,
            feedbackHideBelow = p[hideBelowKey],
        )
    }

    suspend fun currentDecisionModel(): DecisionModelSettings = decisionModel.first()

    suspend fun saveDecisionModel(settings: DecisionModelSettings) {
        context.deviceSettingsStore.edit { p ->
            p[baseUrlKey] = settings.baseUrl.trim().trimEnd('/')
            p[modelKey] = settings.model.trim()
            val hide = settings.feedbackHideBelow
            if (hide == null) p.remove(hideBelowKey) else {
                require(hide in 0.0..1.0) { "The hide threshold must be between 0 and 1" }
                p[hideBelowKey] = hide
            }
        }
    }
}
