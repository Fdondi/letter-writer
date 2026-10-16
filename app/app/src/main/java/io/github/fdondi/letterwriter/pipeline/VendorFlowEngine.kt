package io.github.fdondi.letterwriter.pipeline

import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.ApiKeys
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.data.UserProfile
import io.github.fdondi.letterwriter.decision.DecisionJudge
import io.github.fdondi.letterwriter.decision.DecisionModelClient
import io.github.fdondi.letterwriter.decision.RagJudgement
import io.github.fdondi.letterwriter.decision.StoredFieldNames
import io.github.fdondi.letterwriter.llm.ClientFactory
import io.github.fdondi.letterwriter.llm.LlmClient
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.llm.UsageCollector
import io.github.fdondi.letterwriter.llm.VendorRoleOverrides
import io.github.fdondi.letterwriter.llm.withUsagePhase
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.Collections
import java.util.Locale
import java.util.UUID

/**
 * Runs the vendor flow on the phone: the desktop's `/api/extract/`, `/api/phases/...`,
 * `/api/translate/` and `/api/documents/` handlers, with the session in [WorkSessionStore].
 *
 * Every model call runs inside a cost phase whose usage is queued for BigQuery
 * (`costs.recordPhase`) even when the call fails.
 */
class VendorFlowEngine(private val graph: AppGraph, private val store: WorkSessionStore) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val _loaded = MutableStateFlow(false)
    val loaded: StateFlow<Boolean> = _loaded.asStateFlow()

    val session: StateFlow<WorkSession?> = store.session
        .onEach { _loaded.value = true }
        .stateIn(scope, SharingStarted.Eagerly, null)

    /** Running task key (`extract`, `research`, `vendor:<key>`) to what it is doing right now. */
    private val _running = MutableStateFlow<Map<String, String>>(emptyMap())
    val running: StateFlow<Map<String, String>> = _running.asStateFlow()

    /** Errors from actions that have no place in the session (item edits, snapshots, cost queueing). */
    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message.asStateFlow()

    fun dismissMessage() {
        _message.value = null
    }

    private val generation = LetterGeneration(graph.prompts)
    private val extraction = Extraction(graph.prompts)
    private val checks = FeedbackChecks(graph.prompts, generation::defaultStyle)
    private val translator = Translator(graph.languages)

    private data class Ctx(val sub: String, val profile: UserProfile, val overrides: VendorRoleOverrides, val factory: ClientFactory) {
        fun client(vendor: String): LlmClient =
            factory.create(ModelVendor.fromKey(vendor) ?: throw IllegalArgumentException("Unknown vendor '$vendor'"))
    }

    private fun ctx(): Ctx {
        val sub = graph.auth.requireUser().sub
        val profile = graph.profiles.current()
        val overrides = profile.roleOverrides(graph.modelOverrides)
        return Ctx(sub, profile, overrides, ClientFactory(graph.catalogs, graph.apiKeys.value, overrides))
    }

    // ---- session edits ----

    private suspend fun requireSession(): WorkSession = store.current() ?: throw IllegalStateException("No letter in progress")

    /** Applies [f] only while the session is still [sessionId], so a finished task can't write into a newer letter. */
    private suspend fun edit(sessionId: String, f: (WorkSession) -> WorkSession) {
        store.update { s -> if (s == null || s.sessionId != sessionId) s else f(s) }
    }

    private suspend fun editIntake(sessionId: String, f: (JobIntake) -> JobIntake) = edit(sessionId) { it.copy(intake = f(it.intake)) }

    private suspend fun editVendor(sessionId: String, vendor: String, f: (VendorWork) -> VendorWork) =
        edit(sessionId) { s -> s.copy(work = s.work + (vendor to f(s.vendorWork(vendor)))) }

    private fun fire(what: String, block: suspend () -> Unit) {
        scope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _message.value = "$what failed: ${describe(e)}"
            }
        }
    }

    private fun launchTask(key: String, label: String, onError: suspend (String) -> Unit, block: suspend () -> Unit): Boolean {
        var started = false
        _running.update { if (key in it) it.also { started = false } else it.also { started = true } + (key to label) }
        if (!started) return false
        scope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val msg = describe(e)
                try {
                    onError(msg)
                } catch (inner: Exception) {
                    _message.value = msg
                }
            } finally {
                _running.update { it - key }
            }
        }
        return true
    }

    private fun setLabel(key: String, label: String) = _running.update { if (key in it) it + (key to label) else it }

    /** One cost phase; [attribute] receives the dollars spent so the session can show them. */
    private suspend fun <T> costPhase(sub: String, phase: String, attribute: suspend (Double) -> Unit, block: suspend () -> T): T {
        val collector = UsageCollector(phase)
        try {
            return withUsagePhase(collector) { block() }
        } finally {
            withContext(NonCancellable) {
                try {
                    graph.costs.recordPhase(sub, collector)
                } catch (e: Exception) {
                    _message.value = "Cost of the '$phase' step could not be queued for BigQuery: ${describe(e)}"
                }
                val spent = collector.totals().values.sumOf { it.cost }
                if (spent > 0) attribute(spent)
            }
        }
    }

    private fun intakeCost(sessionId: String, phase: String): suspend (Double) -> Unit = { c ->
        editIntake(sessionId) { it.copy(costs = it.costs.plusCost(phase, c)) }
    }

    private fun vendorCost(sessionId: String, vendor: String, phase: String): suspend (Double) -> Unit = { c ->
        editVendor(sessionId, vendor) { it.copy(costs = it.costs.plusCost(phase, c)) }
    }

    // ---- session lifecycle ----

    /** Replaces any letter in progress and starts extraction on the new job text. */
    fun startLetter(jobText: String, sourceUrl: String, vendors: List<String>, includePlanStep: Boolean) = fire("Starting a new letter") {
        store.update {
            WorkSession(intake = JobIntake(jobText = jobText.trim(), sourceUrl = sourceUrl), vendors = vendors, includePlanStep = includePlanStep)
        }
        extract()
    }

    fun discardSession() = fire("Discarding the letter") { store.update { null } }

    fun updateIntake(f: (JobIntake) -> JobIntake) = fire("Saving job details") {
        val id = requireSession().sessionId
        editIntake(id, f)
    }

    fun setVendors(vendors: List<String>, includePlanStep: Boolean) = fire("Saving vendors") {
        val id = requireSession().sessionId
        edit(id) { it.copy(vendors = vendors, includePlanStep = includePlanStep) }
    }

    fun toggleDocument(key: String) = updateIntake { i ->
        i.copy(selectedDocIds = if (key in i.selectedDocIds) i.selectedDocIds - key else i.selectedDocIds + key)
    }

    fun selectReport(model: String) = updateIntake { i ->
        val report = i.companyReports[model].asObjectOrNull()?.get("report").asStringOrNull().orEmpty()
        i.copy(selectedReportModel = model, companyReport = report)
    }

    // ---- extract ----

    /** `/api/extract/` plus the company/role metadata call, all in cost phase `extract`. */
    fun extract(): Boolean = launchTask(
        "extract",
        "Reading the job offer",
        onError = { msg -> requireSession().let { s -> editIntake(s.sessionId) { it.copy(warnings = it.warnings + "Extraction failed: $msg") } } },
    ) {
        val s = requireSession()
        val id = s.sessionId
        val c = ctx()
        val jobText = s.intake.jobText.trim()
        require(jobText.isNotEmpty()) { "Paste the job offer first." }
        val vendor = ModelVendor.fromKey(c.profile.extractionVendor) ?: throw IllegalStateException("Unknown extraction vendor '${c.profile.extractionVendor}'")
        val client = c.factory.create(vendor)
        val warnings: MutableList<String> = Collections.synchronizedList(ArrayList())

        val result = costPhase(c.sub, "extract", intakeCost(id, "extract")) {
            coroutineScope {
                val meta = async { extraction.metadata(jobText, client) }
                val comp = async { competenceStep(jobText, c.profile, client) }
                val rag = async { ragStep(c.sub, jobText, client, warnings) }
                Triple(meta.await(), comp.await(), rag.await())
            }
        }
        val (metaPair, compPair, ragResult) = result
        val (meta, metaWarning) = metaPair
        val (competences, compWarnings) = compPair
        metaWarning?.let { warnings += it }
        warnings += compWarnings

        editIntake(id) { i ->
            fun pick(key: String, current: String) = meta[key].asStringOrNull()?.takeIf { it.isNotEmpty() } ?: current
            i.copy(
                companyName = pick("company_name", i.companyName),
                jobTitle = pick("job_title", i.jobTitle),
                location = pick("location", i.location),
                language = pick("language", i.language),
                salary = pick("salary", i.salary),
                pointOfContact = meta["point_of_contact"].asObjectOrNull() ?: i.pointOfContact,
                competences = competences.competences,
                requirements = competences.requirements,
                hireProblem = competences.hireProblem,
                similarDocuments = ragResult.similar,
                selectedDocIds = ragResult.topIds,
                decisionDetail = ragResult.decisionDetail,
                extracted = true,
                warnings = warnings.toList(),
            )
        }
    }

    private data class CompetenceStep(val competences: JsonObject, val requirements: List<String>, val hireProblem: String)

    private suspend fun competenceStep(jobText: String, profile: UserProfile, client: LlmClient): Pair<CompetenceStep, List<String>> {
        val warnings = ArrayList<String>()
        val (extracted, w1) = extraction.competences(jobText, client)
        w1?.let { warnings += it }
        val (pairs, matched, unmatched) = extraction.processCompetences(extracted.byCategory, profile.competenceRatings)
        val (graded, w2) = extraction.grade(unmatched, profile.cvWithExtraInfo(), client)
        w2?.let { warnings += it }
        val default = CompetenceScale.defaultLevel()
        val competences = buildJsonObject {
            for ((skill, need) in pairs) {
                put(skill, buildJsonObject {
                    put("need", need)
                    put("level", matched[skill] ?: graded[skill] ?: default)
                })
            }
        }
        return CompetenceStep(competences, pairs.map { it.first }, extracted.hireProblem) to warnings
    }

    private data class RagStep(val similar: List<JsonObject>, val topIds: List<String>, val decisionDetail: String)

    /** Similar letters, then rerank + decision-model rescoring. Failures become warnings (the desktop only logs them). */
    private suspend fun ragStep(sub: String, jobText: String, client: LlmClient, warnings: MutableList<String>): RagStep {
        val raw = try {
            graph.documents.similar(sub, jobText).map { it.document.data }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            warnings += "Similar letters could not be loaded: ${describe(e)}"
            return RagStep(emptyList(), emptyList(), "")
        }
        val sanitized = Extraction.sanitize(raw)
        if (raw.isEmpty()) return RagStep(sanitized, emptyList(), "")
        val top = try {
            extraction.selectTopDocuments(raw, jobText, client) { reranked ->
                val (dc, detail) = graph.decisionModelClient()
                val (status, judged) = graph.decisionJudge.applyRagScores(dc, detail, jobText, reranked)
                judged.mapValues { (_, j) -> j.score to ragExtraFields(j) } to status.detail
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            warnings += "Ranking similar letters failed, so none is pre-selected: ${describe(e)}"
            return RagStep(sanitized, emptyList(), "")
        }
        val enriched = sanitized.map { doc ->
            val company = (doc["company_name_original"].asStringOrNull()?.takeIf { it.isNotEmpty() } ?: doc["company_name"].asStringOrNull().orEmpty()).trim()
            if (company.isEmpty()) return@map doc
            val m = LinkedHashMap(doc)
            top.allScores[company]?.let { m["score"] = JsonPrimitive(it) }
            top.scoreDetails[company]?.let { m.putAll(it) }
            top.allBriefs[company]?.let { b ->
                m["similarities"] = b["similarities"] ?: JsonArray(emptyList())
                m["differences"] = b["differences"] ?: JsonArray(emptyList())
            }
            JsonObject(m)
        }
        return RagStep(enriched, top.topDocs.map { WorkSession.docKey(it) }, top.decisionDetail)
    }

    // ---- research ----

    /** Company report (and point-of-contact report when a name is known), cost phase `background`. */
    fun research(): Boolean = launchTask(
        "research",
        "Researching the company",
        onError = { msg -> requireSession().let { s -> editIntake(s.sessionId) { it.copy(warnings = it.warnings + "Research failed: $msg") } } },
    ) {
        val s = requireSession()
        val id = s.sessionId
        val c = ctx()
        val company = s.intake.companyName.trim()
        require(company.isNotEmpty()) { "Enter the company name first." }
        val (models, dropped) = c.profile.backgroundModels(graph.catalogs)
        val warnings = ArrayList<String>()
        if (dropped.isNotEmpty()) warnings += "Skipped research models the phone can't run (no web search or desktop-only): ${dropped.joinToString(", ")}"
        val research = Research(graph.prompts, graph.companies, { c.factory.create(it) }, { c.overrides }, graph.modelOverrides)
        val search = c.profile.searchInstructions().trim().ifEmpty { graph.prompts.load("defaults/search_instructions.txt").trim() }
        val pocName = s.intake.pointOfContact?.get("name").asStringOrNull()?.trim().orEmpty()

        val (companyResult, pocResult) = costPhase(c.sub, "background", intakeCost(id, "background")) {
            coroutineScope {
                val cr = async { research.company(company, models, s.intake.jobText, s.intake.additionalCompanyInfo, search) }
                val pr = async { if (pocName.isNotEmpty()) research.pointOfContact(pocName, models, company, s.intake.jobText) else null }
                cr.await() to pr.await()
            }
        }
        warnings += companyResult.warnings
        pocResult?.second?.let { warnings += it }
        val reports = companyResult.results
        val firstOk = reports.entries.firstOrNull { (_, v) -> v.asObjectOrNull()?.get("report").asStringOrNull()?.isNotBlank() == true }
        if (firstOk == null) {
            val errors = reports.entries.joinToString("; ") { (m, v) -> "$m: ${v.asObjectOrNull()?.get("error").pyStr()}" }
            warnings += "No research model produced a report${if (errors.isNotEmpty()) " ($errors)" else ""}."
        }
        editIntake(id) { i ->
            i.copy(
                companyReports = reports,
                researchSource = companyResult.source,
                selectedReportModel = firstOk?.key,
                companyReport = firstOk?.value?.asObjectOrNull()?.get("report").asStringOrNull().orEmpty(),
                pocReports = pocResult?.first ?: i.pocReports,
                warnings = i.warnings + warnings,
            )
        }
    }

    // ---- vendor flow ----

    private fun vendorKey(vendor: String) = "vendor:$vendor"

    private fun vendorError(vendor: String): suspend (String) -> Unit = { msg ->
        val s = requireSession()
        editVendor(s.sessionId, vendor) { it.copy(error = msg) }
    }

    /** `get_effective_additional_user_info`. */
    private fun effectiveAdditionalUserInfo(base: String, profile: UserProfile): String {
        val appendix = UserProfile.formatAgentFeedbackContextForPrompt(profile.agentFeedbackContext)
        if (appendix.isBlank()) return base
        if (base.isBlank()) return appendix
        return base.trimEnd() + "\n\n---\n\nSaved notes for model context (from feedback):\n\n" + appendix
    }

    private fun inputs(s: WorkSession, profile: UserProfile): LetterInputs = LetterInputs(
        cvText = profile.cvWithExtraInfo(),
        jobText = s.intake.jobText,
        companyReport = s.intake.companyReport,
        topDocs = s.selectedTopDocs(),
        additionalUserInfo = effectiveAdditionalUserInfo(s.intake.additionalUserInfo, profile),
        hireProblem = s.intake.hireProblem,
        languagePrefix = graph.languages.systemPrefix(profile.data, s.intake.language),
        styleInstructions = profile.styleInstructions(),
        structureInstructions = profile.structureInstructions(),
    )

    /** Plan first when the session includes the plan step, otherwise straight to the draft. */
    fun startVendor(vendor: String): Boolean = launchTask(vendorKey(vendor), "Starting", vendorError(vendor)) {
        val s = requireSession()
        editVendor(s.sessionId, vendor) { VendorWork(vendor) }
        if (s.includePlanStep) runPlan(vendor) else runDraft(vendor, "")
    }

    fun redoPlan(vendor: String): Boolean = launchTask(vendorKey(vendor), "Planning", vendorError(vendor)) { runPlan(vendor) }

    fun approvePlan(vendor: String, plan: String): Boolean = launchTask(vendorKey(vendor), "Writing the draft", vendorError(vendor)) {
        runDraft(vendor, plan.trim())
    }

    fun redoDraft(vendor: String): Boolean = launchTask(vendorKey(vendor), "Writing the draft", vendorError(vendor)) {
        runDraft(vendor, requireSession().vendorWork(vendor).letterPlan)
    }

    /** Runs the draft-phase checks and review on the letter already written. Does not write a new draft. */
    fun checkDraft(vendor: String): Boolean = launchTask(vendorKey(vendor), "Checking the draft", vendorError(vendor)) {
        runFeedbackOnDraft(vendor, null)
    }

    /**
     * Draft-phase Approve (`/api/phases/refine/`): rewrite with the comments the user accepted.
     * [LetterGeneration.rewrite] returns the draft unchanged when nothing needs fixing.
     * An empty result is an error; the draft is not copied in its place.
     */
    fun approveDraft(vendor: String, fancy: Boolean): Boolean = launchTask(vendorKey(vendor), "Rewriting", vendorError(vendor)) {
        val w = requireSession().vendorWork(vendor)
        val draft = w.draftEdited?.takeIf { it.isNotBlank() } ?: w.draftLetter
        require(draft.isNotBlank()) { "Draft letter is missing" }
        require(w.allApproved()) { "Approve every comment before approving the draft" }
        runRefine(vendor, fancy)
    }

    private suspend fun runPlan(vendor: String) {
        val s = requireSession()
        val c = ctx()
        setLabel(vendorKey(vendor), "Planning")
        val plan = costPhase(c.sub, "plan", vendorCost(s.sessionId, vendor, "plan")) {
            generation.plan(inputs(s, c.profile), c.client(vendor))
        }
        editVendor(s.sessionId, vendor) { it.copy(stage = VendorStage.PLAN, letterPlan = plan, error = null) }
    }

    /** `advance_to_draft`: letter, the 7 checks with quote spans and decision scoring, review, cross-vendor input clusters. */
    private suspend fun runDraft(vendor: String, plan: String) {
        val s = requireSession()
        val id = s.sessionId
        val c = ctx()
        val key = vendorKey(vendor)
        val client = c.client(vendor)
        val inputs = inputs(s, c.profile)

        setLabel(key, "Writing the draft")
        val (letter, known) = costPhase(c.sub, "draft", vendorCost(id, vendor, "draft")) { generation.draft(inputs, plan, client) }
        editVendor(id, vendor) {
            VendorWork(vendor, stage = VendorStage.DRAFT, letterPlan = plan, draftLetter = letter, knownWeaknesses = known, costs = it.costs)
        }

        runFeedbackOnDraft(vendor, letter)
    }

    /**
     * The feedback half of `advance_to_draft`: seven checks, quote spans, decision scoring, review,
     * then cross-vendor input clusters. [letter] is the text just generated; a later check uses the
     * draft the user is looking at, including their edits.
     */
    private suspend fun runFeedbackOnDraft(vendor: String, letter: String?) {
        val s = requireSession()
        val id = s.sessionId
        val c = ctx()
        val key = vendorKey(vendor)
        val client = c.client(vendor)
        val inputs = inputs(s, c.profile)
        val vw = s.vendorWork(vendor)
        val text = letter?.takeIf { it.isNotBlank() }
            ?: vw.draftEdited?.takeIf { it.isNotBlank() }
            ?: vw.draftLetter
        require(text.isNotBlank()) { "Draft letter is missing; write a draft first" }
        val known = vw.knownWeaknesses

        val warnings: MutableList<String> = Collections.synchronizedList(ArrayList())
        setLabel(key, "Checking the draft")
        val (annotated, checkErrors) = costPhase(c.sub, "feedback", vendorCost(id, vendor, "feedback")) {
            val results = checks.runAll(text, inputs, known, client)
            val spans = QuoteSpans { graph.embeddings.embedBatch(it) }
            val attached = spans.attachToFeedback(results.mapValues { it.value.items }, text)
            spans.failures.forEach { warnings += "Quote matching: $it" }
            val (dc, detail) = graph.decisionModelClient()
            val hideBelow = graph.deviceSettings.currentDecisionModel().feedbackHideBelow
            val (status, ann) = graph.decisionJudge.annotateFeedbackValidity(dc, detail, FeedbackItems.toJson(attached), text, hideBelow)
            if (!status.available) warnings += "Comments were not checked by the decision model: ${status.detail}"
            ann to results.mapNotNull { (cat, r) -> r.error?.let { cat to it } }.toMap()
        }

        setLabel(key, "Reviewing the comments")
        costPhase(c.sub, "feedback_review", vendorCost(id, vendor, "feedback_review")) {
            val review = FeedbackReview(graph.prompts, checks, generation::defaultStyle)
            val reviewed = review.reviewForVendor(client, text, annotated.mapValues { it.value.feedbackList() }, inputs, vendor, known)
            warnings += review.warnings
            editVendor(id, vendor) {
                it.copy(
                    feedback = FeedbackItems.toJson(reviewed),
                    feedbackOverrides = JsonObject(emptyMap()),
                    itemApprovals = emptyMap(),
                    checkErrors = checkErrors,
                    warnings = warnings.toList(),
                    error = null,
                )
            }
            mergeClustersAcrossVendors(id, client, inputs.topDocs)
        }
    }

    /**
     * `merge_input_clusters_across_session_vendors` over every vendor that has feedback.
     * A vendor whose feedback changed while the call ran keeps its own version, with a warning.
     */
    private suspend fun mergeClustersAcrossVendors(sessionId: String, client: LlmClient, topDocs: List<JsonObject>) {
        val snapshot = requireSession()
        val withFeedback = snapshot.work.filterValues { it.feedback.isNotEmpty() }
        if (withFeedback.size < 2) return
        val review = FeedbackReview(graph.prompts, checks, generation::defaultStyle)
        val merged = review.mergeInputClustersAcrossVendors(
            client,
            withFeedback.mapValues { (_, w) -> w.feedback.mapValues { it.value.feedbackList() } },
            withFeedback.mapValues { topDocs },
        )
        edit(sessionId) { s ->
            val work = s.work.toMutableMap()
            for ((v, fb) in merged) {
                val current = work[v] ?: continue
                work[v] = if (current.feedback == withFeedback[v]?.feedback) {
                    current.copy(feedback = FeedbackItems.toJson(fb), warnings = current.warnings + review.warnings)
                } else {
                    current.copy(warnings = current.warnings + "Shared input questions were not linked across vendors because this vendor's comments changed meanwhile.")
                }
            }
            s.copy(work = work)
        }
    }

    /** `advance_to_refinement`: overrides merged over the feedback, normalized, rewrite, optional fancy pass. */
    fun refine(vendor: String, fancy: Boolean): Boolean = launchTask(vendorKey(vendor), "Rewriting", vendorError(vendor)) {
        runRefine(vendor, fancy)
    }

    private suspend fun runRefine(vendor: String, fancy: Boolean) {
        val s = requireSession()
        val c = ctx()
        val vw = s.vendorWork(vendor)
        val draft = vw.draftEdited?.takeIf { it.isNotBlank() } ?: vw.draftLetter
        require(draft.isNotBlank()) { "Missing draft letter for refinement" }
        val inputs = inputs(s, c.profile)
        val client = c.client(vendor)
        val feedback = FeedbackItems.normalizeMap(vw.mergedFeedback(), inputs.topDocs)
        val refined = costPhase(c.sub, "refine", vendorCost(s.sessionId, vendor, "refine")) {
            var out = generation.rewrite(draft, feedback.mapValues { JsonArray(it.value) }, client, vw.letterPlan, inputs.styleInstructions, inputs.languagePrefix)
            if (fancy) out = generation.fancy(out, client)
            out
        }
        require(refined.isNotBlank()) { "Refinement returned an empty letter" }
        editVendor(s.sessionId, vendor) { it.copy(stage = VendorStage.FINAL, finalLetter = refined, error = null) }
    }

    fun editPlan(vendor: String, plan: String) = fire("Saving the plan") {
        editVendor(requireSession().sessionId, vendor) { it.copy(letterPlan = plan) }
    }

    fun editDraft(vendor: String, text: String) = fire("Saving the draft") {
        editVendor(requireSession().sessionId, vendor) { it.copy(draftEdited = text) }
    }

    fun editFinal(vendor: String, text: String) = fire("Saving the letter") {
        editVendor(requireSession().sessionId, vendor) { it.copy(finalLetter = text) }
    }

    fun rate(vendor: String, rating: Int?, comment: String) = fire("Saving the rating") {
        editVendor(requireSession().sessionId, vendor) { it.copy(rating = rating, comment = comment) }
    }

    // ---- feedback items ----

    /** Saves one category's edited list as an override, then posts the draft-feedback snapshot like the desktop. */
    private suspend fun saveItems(vendor: String, category: String, approvals: ((Map<String, Boolean>) -> Map<String, Boolean>)? = null, transform: (List<JsonObject>) -> List<JsonObject>) {
        val s = requireSession()
        val c = ctx()
        editVendor(s.sessionId, vendor) { w ->
            val next = transform(w.items(category))
            w.copy(
                feedbackOverrides = JsonObject(w.feedbackOverrides + (category to JsonArray(next))),
                itemApprovals = approvals?.invoke(w.itemApprovals) ?: w.itemApprovals,
            )
        }
        val after = requireSession()
        val w = after.vendorWork(vendor)
        graph.documents.savePhaseDraftFeedbackSnapshot(
            c.sub,
            after.sessionId,
            after.documentId,
            vendor,
            StoredFieldNames.toStored(w.feedback) as JsonObject,
            StoredFieldNames.toStored(w.feedbackOverrides) as JsonObject,
        )
    }

    private fun allItems(w: VendorWork): List<JsonObject> = FeedbackItems.CATEGORIES.flatMap { w.items(it) }

    private fun JsonObject.with(vararg pairs: Pair<String, JsonElement>): JsonObject = JsonObject(this + pairs)

    private fun JsonObject.idText(): String = this["id"].pyStr()

    private suspend fun linked(vendor: String, category: String, itemId: String): Set<String> {
        val w = requireSession().vendorWork(vendor)
        val item = w.items(category).firstOrNull { it.idText() == itemId } ?: return setOf(itemId)
        return FeedbackUi.linkedIds(item, allItems(w))
    }

    /** `onApprovePleaseFix`: input-needed items need an answer or a decline first; hidden items come back. */
    fun approveItem(vendor: String, category: String, itemId: String) = fire("Approving the comment") {
        val w = requireSession().vendorWork(vendor)
        val item = w.items(category).firstOrNull { it.idText() == itemId } ?: return@fire
        if (item["status"].pyStr().uppercase() == "INPUT_NEEDED") {
            val filled = item["user_context"].pyStr().isNotBlank()
            val declined = item["input_declined"].asBooleanOrNull() == true
            if (!filled && !declined) return@fire
        }
        val ids = linked(vendor, category, itemId)
        saveItems(vendor, category, approvals = { a -> a + ids.associateWith { true } }) { items ->
            items.map { if (it.idText() == itemId) FeedbackUi.withRestored(it) else it }
        }
    }

    fun unapproveItem(vendor: String, category: String, itemId: String) = fire("Updating the comment") {
        val s = requireSession()
        val ids = linked(vendor, category, itemId)
        editVendor(s.sessionId, vendor) { w -> w.copy(itemApprovals = w.itemApprovals + ids.associateWith { false }) }
    }

    fun editObservation(vendor: String, category: String, itemId: String, observation: String) = fire("Saving the comment") {
        saveItems(vendor, category) { items ->
            items.map { if (it.idText() == itemId) FeedbackUi.withRestored(it.with("observation" to JsonPrimitive(observation))) else it }
        }
    }

    fun addItem(vendor: String, category: String) = fire("Adding a comment") {
        saveItems(vendor, category) { items ->
            items + buildJsonObject {
                put("id", UUID.randomUUID().toString())
                put("observation", "")
                put("type", FeedbackUi.PLEASE_FIX)
                put("status", "NOT_NEEDED")
            }
        }
    }

    fun removeItem(vendor: String, category: String, itemId: String) = fire("Removing the comment") {
        saveItems(vendor, category, approvals = { it - itemId }) { items -> items.filter { it.idText() != itemId } }
    }

    /** `commitInputNeededDraft`: the answer, its persistence scope, cluster broadcast, linked approval. */
    fun answerInput(vendor: String, category: String, itemId: String, text: String, toCv: Boolean, toAgents: Boolean) = fire("Saving the answer") {
        if (text.isBlank()) return@fire
        val w = requireSession().vendorWork(vendor)
        val item = w.items(category).firstOrNull { it.idText() == itemId } ?: return@fire
        val ids = linked(vendor, category, itemId)
        saveItems(vendor, category, approvals = { a -> a + ids.associateWith { true } }) { items ->
            items.map {
                if (it.idText() != itemId) it
                else FeedbackUi.withRestored(
                    it.with(
                        "user_context" to JsonPrimitive(text),
                        "input_declined" to JsonPrimitive(false),
                        "persist_user_context_to_cv" to JsonPrimitive(toCv),
                        "persist_user_context_for_agents" to JsonPrimitive(toAgents),
                    ),
                )
            }
        }
        val cluster = item["input_cluster_key"].pyStr().trim()
        if (cluster.isNotEmpty()) {
            edit(requireSession().sessionId) { it.copy(inputClusterText = it.inputClusterText + (cluster to text)) }
        }
    }

    /** `approveWithoutInput`. */
    fun declineInput(vendor: String, category: String, itemId: String) = fire("Skipping the question") {
        val ids = linked(vendor, category, itemId)
        saveItems(vendor, category, approvals = { a -> a + ids.associateWith { true } }) { items ->
            items.map { if (it.idText() == itemId) FeedbackUi.withRestored(it.with("input_declined" to JsonPrimitive(true))) else it }
        }
    }

    /** `setContextItems`: rows replace the item's context; status follows whether any rows are left. */
    fun setContextRows(vendor: String, category: String, itemId: String, rows: List<JsonObject>) = fire("Saving context") {
        saveItems(vendor, category) { items -> items.map { if (it.idText() == itemId) withContextRows(it, rows) else it } }
    }

    private fun withContextRows(item: JsonObject, rows: List<JsonObject>): JsonObject {
        val status = item["status"].pyStr().uppercase()
        val nextStatus = when {
            status == "INPUT_NEEDED" -> "INPUT_NEEDED"
            rows.isNotEmpty() -> "SUFFICIENT"
            else -> "NOT_NEEDED"
        }
        val cf = item["context_field"].asObjectOrNull() ?: JsonObject(emptyMap())
        return item.with("status" to JsonPrimitive(nextStatus), "context_field" to JsonObject(cf + ("items" to JsonArray(rows))))
    }

    /**
     * `/api/phases/feedback/request-context/`: asks the vendor for context lines the check missed
     * and appends the new ones. Returns how many were added. Cost phase `feedback`.
     */
    suspend fun requestContext(vendor: String, category: String, itemId: String): Int {
        val s = requireSession()
        val c = ctx()
        val w = s.vendorWork(vendor)
        val draft = w.draftLetter.trim()
        require(draft.isNotEmpty()) { "Draft letter is missing; run draft first" }
        val item = w.items(category).firstOrNull { it.idText() == itemId } ?: throw IllegalArgumentException("Feedback item not found")
        val obs = item["observation"].pyStr().trim()
        require(obs.isNotEmpty()) { "Item has no observation text" }
        val existing = FeedbackItems.contextItems(item)
        val incoming = costPhase(c.sub, "feedback", vendorCost(s.sessionId, vendor, "feedback")) {
            checks.suggestContext(category, obs, existing, draft, inputs(s, c.profile), c.client(vendor))
        }
        val seen = existing.map { (if (it is JsonObject) it["text"].pyStr() else it.pyStr()).trim().lowercase() }.filter { it.isNotEmpty() }.toMutableSet()
        val appended = ArrayList<JsonObject>()
        for (row in incoming) {
            val text = row["text"].pyStr().trim()
            if (text.isEmpty() || !seen.add(text.lowercase())) continue
            val src = row["source"].pyStr().trim().uppercase().let { if (it in FeedbackUi.CONTEXT_SOURCES) it else "CV" }
            appended += buildJsonObject {
                put("text", text)
                put("source", src)
            }
        }
        if (appended.isEmpty()) return 0
        val rows = existing.mapNotNull { it.asObjectOrNull() } + appended
        saveItems(vendor, category) { items -> items.map { if (it.idText() == itemId) withContextRows(it, rows) else it } }
        return appended.size
    }

    // ---- assembly ----

    private fun editParagraphs(f: (List<FinalParagraph>) -> List<FinalParagraph>) = fire("Updating the letter") {
        edit(requireSession().sessionId) { it.copy(paragraphs = f(it.paragraphs)) }
    }

    fun addParagraph(vendor: String, text: String) = editParagraphs { it + FinalParagraph(vendor = vendor, originalText = text, text = text) }

    fun updateParagraph(id: String, text: String) = editParagraphs { ps -> ps.map { if (it.id == id) it.copy(text = text) else it } }

    fun removeParagraph(id: String) = editParagraphs { ps -> ps.filter { it.id != id } }

    fun moveParagraph(id: String, delta: Int) = editParagraphs { ps ->
        val i = ps.indexOfFirst { it.id == id }
        val j = i + delta
        if (i < 0 || j !in ps.indices) ps else ps.toMutableList().also { it.add(j, it.removeAt(i)) }
    }

    /** Replaces the assembly with one vendor's letter, one paragraph per blank-line block. */
    fun useWholeLetter(vendor: String) = fire("Using the letter") {
        val s = requireSession()
        val text = s.vendorWork(vendor).finalLetter
        val paras = text.split(Regex("\\n\\s*\\n")).map { it.trim() }.filter { it.isNotEmpty() }
        edit(s.sessionId) { it.copy(paragraphs = paras.map { p -> FinalParagraph(vendor = vendor, originalText = p, text = p) }) }
    }

    // ---- translate ----

    /** `/api/translate/`: Google (billed per character) or Gemini (cost phase `translate`), per the profile setting. */
    suspend fun translate(text: String, target: String, source: String? = null): Translation {
        val c = ctx()
        return when (graph.languages.translationProvider(c.profile.data)) {
            "llm" -> costPhase(c.sub, "translate", { }) {
                translator.llm(text, target, source, c.profile.data, null, null, c.factory.create(ModelVendor.GEMINI))
            }
            else -> {
                val key = graph.apiKeys.value.require(ApiKeys.GOOGLE_TRANSLATE, "Google Translate")
                translator.google(text, target, source, key, c.profile.data, null, null) { chars ->
                    graph.costs.recordTranslation(c.sub, chars)
                }
            }
        }
    }

    // ---- decision model ----

    /**
     * One grounding call to check the decision-model settings. Uses the first PLEASE_FIX
     * comment of the letter in progress, or a fixed sample comment when there is none
     * (the result says which). Cost phase `decision_model_test`.
     */
    suspend fun testDecisionModel(): String {
        val c = ctx()
        val (client, detail) = graph.decisionModelClient()
        if (client == null) throw IllegalStateException(detail)
        val s = store.current()
        val real = s?.vendors?.asSequence()?.mapNotNull { v ->
            val w = s.vendorWork(v)
            FeedbackItems.CATEGORIES.asSequence().flatMap { cat -> w.items(cat).map { cat to it }.asSequence() }
                .firstOrNull { (_, it) -> it["type"].pyStr() == FeedbackUi.PLEASE_FIX && it["observation"].pyStr().isNotBlank() }
                ?.let { Triple(w.draftLetter, it.first, it.second) }
        }?.firstOrNull()
        val (letter, category, item) = real ?: Triple(
            TEST_LETTER,
            "accuracy",
            buildJsonObject {
                put("observation", TEST_OBSERVATION)
                put("quote", TEST_QUOTE)
            },
        )
        val questions = graph.prompts.loadJson("decision_model/questions.json").asObjectOrNull()?.get("feedback").asObjectOrNull()
            ?: throw IllegalStateException("decision_model/questions.json has no 'feedback' question set")
        val r = costPhase(c.sub, "decision_model_test", { }) { client.decide(DecisionJudge.feedbackState(letter, item, category), questions) }
        val p = DecisionModelClient.noulAnswer(r, "grounded")
        val what = if (real != null) "the first comment of the letter in progress" else "a built-in sample comment (no letter in progress)"
        return "${r.model} at ${client.device} answered: grounded with probability ${String.format(Locale.US, "%.2f", p)} for $what."
    }

    // ---- save ----

    /**
     * `handlePersistFinalLetter`: document upsert, one `feedbacks` record per vendor letter,
     * and the feedback answers merged into the profile's extra_info / agent_feedback_context.
     */
    suspend fun saveLetter(): String {
        val s = requireSession()
        val c = ctx()
        val letter = s.finalText
        require(letter.isNotEmpty()) { "No letter text to save" }
        val aiLetters = JsonArray(
            s.vendors.mapNotNull { v -> s.work[v]?.takeIf { it.finalLetter.isNotBlank() } }.map { w ->
                val chunks = s.paragraphs.filter { it.vendor == w.vendor }
                buildJsonObject {
                    put("vendor", w.vendor)
                    put("text", w.finalLetter)
                    put("cost", w.totalCost)
                    w.rating?.let { put("rating", it) }
                    put("comment", w.comment)
                    put("chunks_used", chunks.size)
                    put("user_corrections", JsonArray(chunks.filter { it.text != it.originalText }.map { correction(it) }))
                }
            },
        )
        val payload = buildJsonObject {
            s.documentId?.let { put("id", it) }
            put("company_name", s.intake.companyName)
            put("role", s.intake.jobTitle)
            put("location", s.intake.location)
            put("language", s.intake.language)
            put("salary", s.intake.salary)
            put("source_url", s.intake.sourceUrl)
            put("requirements", JsonArray(s.intake.requirements.map(::JsonPrimitive)))
            put("job_text", s.intake.jobText)
            put("letter_text", letter)
            put("ai_letters", aiLetters)
        }
        val doc = graph.documents.upsert(c.sub, payload)
        edit(s.sessionId) { it.copy(documentId = doc.id) }
        if (aiLetters.isNotEmpty()) graph.documents.saveFeedback(c.sub, doc.id, letter, aiLetters)

        var extra = emptyList<JsonObject>()
        var agent = emptyList<JsonObject>()
        for (v in s.vendors) {
            val w = s.work[v] ?: continue
            if (w.feedback.isEmpty()) continue
            val byCat = w.itemsByCategory()
            extra = FeedbackUi.mergeRows(extra, byCat, FeedbackUi::extraInfoRow)
            agent = FeedbackUi.mergeRows(agent, byCat, FeedbackUi::agentContextRow)
        }
        graph.profiles.mergeFeedbackExtraInfo(c.sub, extra)
        graph.profiles.mergeFeedbackAgentContext(c.sub, agent)
        graph.profiles.load(c.sub)
        graph.costs.flush(savingUserId = c.sub)
        return doc.id
    }

    /**
     * One edited paragraph as a correction. The desktop diffs sentences (jsdiff) and stores only
     * the changed regions unless over half the words changed; the phone always stores the whole paragraph.
     */
    private fun correction(p: FinalParagraph): JsonObject = buildJsonObject {
        put("type", "full")
        put("original", p.originalText)
        put("edited", p.text)
    }

    companion object {
        private const val TEST_LETTER = "Dear hiring team,\n\nI led the migration of our billing system to Kotlin, cutting incident volume by half.\n\nKind regards"
        private const val TEST_QUOTE = "cutting incident volume by half"
        private const val TEST_OBSERVATION = "The letter claims incidents were cut by half, but the CV gives no figure for this."

        fun describe(e: Throwable): String = e.message?.takeIf { it.isNotBlank() } ?: e::class.simpleName.orEmpty()

        private fun Map<String, Double>.plusCost(phase: String, cost: Double): Map<String, Double> = this + (phase to ((this[phase] ?: 0.0) + cost))

        /** Rerank row fields from the decision model (`apply_laya_rag_scores`), nulls omitted. */
        fun ragExtraFields(j: RagJudgement): JsonObject = buildJsonObject {
            put("llm_score", j.llmScore)
            j.decisionScore?.let { put("decision_score", it) }
            j.confidence?.let { put("decision_confidence", it) }
            put("score_source", j.source)
            j.device?.let { put("decision_device", it) }
            j.error?.let { put("decision_error", it) }
            j.model?.let { put("decision_model", it) }
        }
    }
}
