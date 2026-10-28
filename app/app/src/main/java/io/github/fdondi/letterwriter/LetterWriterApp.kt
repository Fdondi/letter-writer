package io.github.fdondi.letterwriter

import android.app.Application
import io.github.fdondi.letterwriter.auth.AuthGateway
import io.github.fdondi.letterwriter.auth.AuthManager
import io.github.fdondi.letterwriter.core.AndroidSharedAssets
import io.github.fdondi.letterwriter.core.ApiKeys
import io.github.fdondi.letterwriter.core.CrashLog
import io.github.fdondi.letterwriter.core.DeviceSettings
import io.github.fdondi.letterwriter.core.KeepAlive
import io.github.fdondi.letterwriter.core.Prompts
import io.github.fdondi.letterwriter.core.SharedAssets
import io.github.fdondi.letterwriter.cost.BigQueryApi
import io.github.fdondi.letterwriter.cost.BigQueryClient
import io.github.fdondi.letterwriter.cost.CostRecorder
import io.github.fdondi.letterwriter.data.CompaniesRepository
import io.github.fdondi.letterwriter.data.CompanyStore
import io.github.fdondi.letterwriter.data.DocumentStore
import io.github.fdondi.letterwriter.data.DocumentsRepository
import io.github.fdondi.letterwriter.data.EmbeddingService
import io.github.fdondi.letterwriter.data.Embeddings
import io.github.fdondi.letterwriter.data.FirestoreOpportunityStore
import io.github.fdondi.letterwriter.data.InstructionDefaults
import io.github.fdondi.letterwriter.data.LanguageSettings
import io.github.fdondi.letterwriter.data.OpportunityStore
import io.github.fdondi.letterwriter.data.ProfileRepository
import io.github.fdondi.letterwriter.data.ProfileStore
import io.github.fdondi.letterwriter.debug.DebugFixtures
import io.github.fdondi.letterwriter.decision.DecisionJudge
import io.github.fdondi.letterwriter.decision.DecisionModelClient
import io.github.fdondi.letterwriter.llm.Catalogs
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelOverrides
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.pipeline.WorkSessionStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.serialization.json.JsonObject
import java.io.File
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.StateFlow
import io.github.fdondi.letterwriter.demo.DemoMode
import io.github.fdondi.letterwriter.demo.DemoData
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking

class LetterWriterApp : Application() {
    private val _graph = MutableStateFlow<AppGraph?>(null)

    /** The current graph; it changes when demo mode is entered or left (screens rebuild on it). */
    val graphs: StateFlow<AppGraph?> = _graph.asStateFlow()
    val graph: AppGraph get() = _graph.value ?: error("LetterWriterApp.onCreate has not run")

    override fun onCreate() {
        super.onCreate()
        CrashLog.install(this)
        use(build(DemoMode.isOn(this)))
    }

    /**
     * Enters or leaves demo mode (remembered across restarts). A no-op when already there.
     * Entering starts the demo afresh; the real account's files are never touched.
     */
    fun setDemoMode(on: Boolean) {
        if (_graph.value?.demo == on) return
        DemoMode.save(this, on)
        if (on) resetDemo()
        use(build(on))
    }

    /** The real account's graph is built once per process (its stores own files); demo graphs are fresh. */
    private var real: AppGraph? = null

    private fun build(demo: Boolean): AppGraph =
        if (demo) AppGraph.demo(this) { setDemoMode(false) } else real ?: AppGraph.firebase(this).also { real = it }

    /** A new demo starts without the previous demo's letter in progress or cost queue. */
    private fun resetDemo() {
        val dir = AppGraph.demoDir(this)
        runBlocking(Dispatchers.IO) { WorkSessionStore.at(AppGraph.workSessionFile(dir)).update { null } }
        dir.resolve("costs").deleteRecursively()
    }

    private fun use(graph: AppGraph) {
        _graph.value = graph
        KeepAlive.watch(this, graph.flow.running)
    }
}

/** Everything that leaves the device: the account, Firestore, BigQuery and embeddings. Tests pass in-memory ones. */
class Backend(
    val auth: AuthGateway,
    val profiles: ProfileStore,
    val documents: DocumentStore,
    val companies: CompanyStore,
    val opportunities: OpportunityStore,
    val embeddings: EmbeddingService,
    val bigQuery: BigQueryApi,
)

/**
 * Process-wide singletons. Screens get them through [LetterWriterApp.graph].
 *
 * [llmOverride] replaces every LLM client (tests); the debug harness uses [fakePaidApis] instead.
 * [dataDir] holds the letter in progress and the cost queue.
 */
class AppGraph(
    val app: Application,
    backendFactory: (AppGraph) -> Backend,
    val llmOverride: ((ModelVendor) -> LlmClient)? = null,
    dataDir: File = app.filesDir,
    /** Demo mode ([DemoMode]): made-up account, in-memory data, fixture replies for every model call. */
    val demo: Boolean = false,
    /** Prompts and catalogs; JVM tests read them from the repository instead of the APK. */
    val assets: SharedAssets = AndroidSharedAssets(app.assets),
    val debugFixtures: DebugFixtures = DebugFixtures.fromAssets(app.assets),
) {
    val prompts = Prompts(assets)
    val catalogs by lazy { Catalogs(assets) }
    val modelOverrides by lazy { ModelOverrides(catalogs) }
    val languages by lazy { LanguageSettings(prompts) }
    val instructionDefaults = InstructionDefaults(prompts)

    /** Keys from `personal_data/{sub}/secrets/api_keys`, loaded after sign-in. */
    val apiKeys = MutableStateFlow(ApiKeys(emptyMap()))

    private val backend by lazy { backendFactory(this) }
    val auth: AuthGateway get() = backend.auth
    val profiles: ProfileStore get() = backend.profiles
    val documents: DocumentStore get() = backend.documents
    val companies: CompanyStore get() = backend.companies
    val opportunities: OpportunityStore get() = backend.opportunities
    val embeddings: EmbeddingService get() = backend.embeddings

    val costs by lazy { CostRecorder(dataDir.resolve("costs/queue.jsonl"), auth, backend.bigQuery) }

    val deviceSettings = DeviceSettings(app)
    val decisionJudge = DecisionJudge { prompts.loadJson("decision_model/questions.json") as JsonObject }

    /**
     * True only in a debug build, and only after the user turns the harness on in Settings.
     * Release builds never take this branch, even if the preference was left on.
     */
    suspend fun fakePaidApis(): Boolean = demo || (BuildConfig.DEBUG && deviceSettings.currentFakePaidApis())

    /** Null with a reason when the decision model can't be used; callers show the reason and leave items unscored. */
    suspend fun decisionModelClient(): Pair<DecisionModelClient?, String> {
        if (fakePaidApis()) return null to "Debug harness is on, so the decision model was not called."
        if (llmOverride != null) return null to "Model calls are replaced in this build, so the decision model was not called."
        val key = apiKeys.value.get(ApiKeys.DECISION_MODEL)
            ?: return null to "No 'decision_model' API key saved. Add it in Settings → API keys."
        return DecisionModelClient(deviceSettings.currentDecisionModel(), key) to ""
    }

    val workSessions = WorkSessionStore.at(workSessionFile(dataDir))
    val flow by lazy { VendorFlowEngine(this, workSessions) }

    /** Text or URL received through the Android share sheet, consumed by the intake screen. */
    val incomingShare = MutableStateFlow<String?>(null)

    companion object {
        /** Demo mode: everything in memory and in its own folder, so a real letter in progress is untouched. */
        fun demo(app: Application, onLeave: () -> Unit): AppGraph =
            AppGraph(app, { g -> DemoData.backend(g, onLeave) }, dataDir = demoDir(app), demo = true)

        fun demoDir(app: Application): File = app.filesDir.resolve("demo")

        fun workSessionFile(dataDir: File): File = dataDir.resolve("datastore/work_session.json")

        /** The real app: Google sign-in, the `letter` Firestore database, BigQuery and OpenAI embeddings. */
        fun firebase(app: Application): AppGraph = AppGraph(app, { g ->
            val auth = AuthManager(app)
            val embeddings = Embeddings { g.apiKeys.value.require(ApiKeys.OPENAI, "embeddings for similar documents") }
            Backend(
                auth = auth,
                profiles = ProfileRepository({ auth.firestore() }, g.instructionDefaults, g.modelOverrides),
                documents = DocumentsRepository({ auth.firestore() }, embeddings),
                companies = CompaniesRepository({ auth.firestore() }, embeddings),
                opportunities = FirestoreOpportunityStore { auth.firestore() },
                embeddings = embeddings,
                bigQuery = BigQueryClient(BuildConfig.GCP_PROJECT, BuildConfig.BIGQUERY_DATASET),
            )
        })
    }
}
