package io.github.fdondi.letterwriter

import android.app.Application
import io.github.fdondi.letterwriter.auth.AuthManager
import io.github.fdondi.letterwriter.core.AndroidSharedAssets
import io.github.fdondi.letterwriter.core.ApiKeys
import io.github.fdondi.letterwriter.core.DeviceSettings
import io.github.fdondi.letterwriter.debug.DebugFixtures
import io.github.fdondi.letterwriter.decision.DecisionJudge
import io.github.fdondi.letterwriter.decision.DecisionModelClient
import kotlinx.serialization.json.JsonObject
import io.github.fdondi.letterwriter.cost.BigQueryClient
import io.github.fdondi.letterwriter.cost.CostRecorder
import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.SharedAssets
import io.github.fdondi.letterwriter.data.CompaniesRepository
import io.github.fdondi.letterwriter.data.DocumentsRepository
import io.github.fdondi.letterwriter.data.Embeddings
import io.github.fdondi.letterwriter.data.LanguageSettings
import io.github.fdondi.letterwriter.data.ProfileRepository
import io.github.fdondi.letterwriter.llm.Catalogs
import io.github.fdondi.letterwriter.llm.ModelOverrides
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.pipeline.WorkSessionStore
import kotlinx.coroutines.flow.MutableStateFlow

class LetterWriterApp : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
    }
}

/** Process-wide singletons. Screens get them through [LetterWriterApp.graph]. */
class AppGraph(val app: Application) {
    val assets: SharedAssets = AndroidSharedAssets(app.assets)
    val prompts = Prompts(assets)
    val catalogs by lazy { Catalogs(assets) }
    val modelOverrides by lazy { ModelOverrides(catalogs) }
    val languages by lazy { LanguageSettings(prompts) }
    val auth = AuthManager(app)
    val costs = CostRecorder(
        queueFile = app.filesDir.resolve("costs/queue.jsonl"),
        auth = auth,
        bigQuery = BigQueryClient(BuildConfig.GCP_PROJECT, BuildConfig.BIGQUERY_DATASET),
    )

    /** Keys from `personal_data/{sub}/secrets/api_keys`, loaded after sign-in. */
    val apiKeys = MutableStateFlow(ApiKeys(emptyMap()))

    val profiles by lazy { ProfileRepository({ auth.firestore() }, prompts, modelOverrides) }
    val embeddings = Embeddings { apiKeys.value.require(ApiKeys.OPENAI, "embeddings for similar documents") }
    val documents by lazy { DocumentsRepository({ auth.firestore() }, embeddings) }
    val companies by lazy { CompaniesRepository({ auth.firestore() }, embeddings) }

    val deviceSettings = DeviceSettings(app)
    val debugFixtures = DebugFixtures.fromAssets(app.assets)
    val decisionJudge = DecisionJudge { prompts.loadJson("decision_model/questions.json") as JsonObject }

    /**
     * True only in a debug build, and only after the user turns the harness on in Settings.
     * Release builds never take this branch, even if the preference was left on.
     */
    suspend fun fakePaidApis(): Boolean = BuildConfig.DEBUG && deviceSettings.currentFakePaidApis()

    /** Null with a reason when the decision model can't be used; callers show the reason and leave items unscored. */
    suspend fun decisionModelClient(): Pair<DecisionModelClient?, String> {
        if (fakePaidApis()) return null to "Debug harness is on, so the decision model was not called."
        val key = apiKeys.value.get(ApiKeys.DECISION_MODEL)
            ?: return null to "No 'decision_model' API key saved. Add it in Settings → API keys."
        return DecisionModelClient(deviceSettings.currentDecisionModel(), key) to ""
    }

    val workSessions = WorkSessionStore(app)
    val flow by lazy { VendorFlowEngine(this, workSessions) }

    /** Text or URL received through the Android share sheet, consumed by the intake screen. */
    val incomingShare = MutableStateFlow<String?>(null)
}
