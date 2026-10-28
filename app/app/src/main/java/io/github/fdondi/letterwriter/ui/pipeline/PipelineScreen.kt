package io.github.fdondi.letterwriter.ui.pipeline

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.data.JobPageFetcher
import io.github.fdondi.letterwriter.data.Opportunity
import io.github.fdondi.letterwriter.data.OpportunityStatus
import io.github.fdondi.letterwriter.pipeline.PipelineSession
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import io.github.fdondi.letterwriter.ui.common.formatDollars
import io.github.fdondi.letterwriter.ui.intake.sendToPipeline
import io.github.fdondi.letterwriter.ui.write.WriteTab
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Tabs over `opportunities.status`, in the order a job moves through them. */
private enum class PipelineTab(val title: String, val statuses: Set<OpportunityStatus>) {
    REVIEW("To review", setOf(OpportunityStatus.PROPOSED)),
    NEEDS_TEXT("Needs text", setOf(OpportunityStatus.APPROVED)),
    QUEUED("Queued", setOf(OpportunityStatus.CAPTURED)),
    RUNNING("Running", setOf(OpportunityStatus.DRAFTING)),
    READY("Ready", setOf(OpportunityStatus.READY)),
    FAILED("Failed", setOf(OpportunityStatus.FAILED)),
    ARCHIVE("Done", setOf(OpportunityStatus.DONE, OpportunityStatus.APPLIED, OpportunityStatus.SKIPPED, OpportunityStatus.UNKNOWN)),
}

private sealed interface Load {
    data object Loading : Load
    data class Loaded(val jobs: List<Opportunity>) : Load
    data class Failed(val message: String) : Load
}

private val SKIP_REASONS = listOf("Not a fit", "Location", "Seniority", "Salary", "Company", "Already applied")

/** Statuses a job can be skipped from: not while the desktop drafts it. */
private val SKIPPABLE = setOf(
    OpportunityStatus.PROPOSED,
    OpportunityStatus.APPROVED,
    OpportunityStatus.CAPTURED,
    OpportunityStatus.FAILED,
    OpportunityStatus.READY,
)

/**
 * The desktop pipeline's jobs (OPPORTUNITY_PIPELINE_PLAN.md): triage proposals, give approved
 * jobs their posting text, and open the drafts of ready ones as the letter in progress.
 * [onOpenLetter] switches to the Write screen at the given [WriteTab].
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PipelineScreen(graph: AppGraph, onOpenLetter: (Int) -> Unit, modifier: Modifier = Modifier) {
    val user by graph.auth.user.collectAsState()
    val sub = user?.sub ?: return
    var retry by remember { mutableIntStateOf(0) }
    val jobsFlow: Flow<Load> = remember(sub, retry) {
        graph.opportunities.observe(sub)
            .map<List<Opportunity>, Load> { Load.Loaded(it) }
            .catch { e -> emit(Load.Failed("Could not load the job pipeline: ${VendorFlowEngine.describe(e)}")) }
    }
    val load by jobsFlow.collectAsState(initial = Load.Loading)
    val session by graph.flow.session.collectAsState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var picked by rememberSaveable { mutableStateOf<PipelineTab?>(null) }
    var busyId by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var adding by remember { mutableStateOf(false) }
    var skipping by remember { mutableStateOf<Opportunity?>(null) }
    var pasting by remember { mutableStateOf<Opportunity?>(null) }
    var replacing by remember { mutableStateOf<Opportunity?>(null) }

    /** Runs [block] for job [id] with a busy row on its card; failures show above the list. */
    fun act(id: String, block: suspend () -> String?) {
        busyId = id
        error = null
        scope.launch {
            try {
                block()?.let { graph.flow.showMessage(it) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                error = VendorFlowEngine.describe(e)
            } finally {
                busyId = null
            }
        }
    }

    fun open(job: Opportunity) = act(job.id) {
        graph.flow.openOpportunity(job)
        // The paragraph review on the Final tab shows the questions next to the text they are about.
        onOpenLetter(WriteTab.FINAL)
        null
    }

    fun requestOpen(job: Opportunity) {
        val current = session
        when {
            current == null -> open(job)
            current.opportunityId == job.id -> onOpenLetter(WriteTab.FINAL)
            else -> replacing = job
        }
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            "Jobs the desktop proposes from your job alerts, and postings you send it. " +
                "The desktop drafts captured jobs on its scheduled run; their letters then appear under Ready.",
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedButton(onClick = { adding = true }) { Text("Add a job") }
        ErrorText(error)
        when (val l = load) {
            Load.Loading -> BusyRow("Loading the job pipeline")
            is Load.Failed -> {
                ErrorText(l.message)
                TextButton(onClick = { retry++ }) { Text("Try again") }
            }
            is Load.Loaded -> {
                val byTab = PipelineTab.entries.associateWith { t -> l.jobs.filter { it.status in t.statuses } }
                val tab = picked ?: listOf(PipelineTab.READY, PipelineTab.RUNNING, PipelineTab.REVIEW, PipelineTab.NEEDS_TEXT, PipelineTab.QUEUED)
                    .firstOrNull { byTab.getValue(it).isNotEmpty() } ?: PipelineTab.READY
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (t in PipelineTab.entries) {
                        val n = byTab.getValue(t).size
                        FilterChip(selected = t == tab, onClick = { picked = t }, label = { Text(if (n > 0) "${t.title} · $n" else t.title) })
                    }
                }
                val jobs = byTab.getValue(tab)
                if (jobs.isEmpty()) Text(emptyText(tab), style = MaterialTheme.typography.bodyMedium)
                for (job in jobs) {
                    key(job.id) {
                        JobCard(
                            job = job,
                            busy = busyId == job.id,
                            isCurrentLetter = session?.opportunityId == job.id,
                            onApprove = {
                                act(job.id) {
                                    graph.opportunities.transition(sub, job.id, setOf(OpportunityStatus.PROPOSED), OpportunityStatus.APPROVED)
                                    "Approved. Add the posting text under Needs text."
                                }
                            },
                            onSkip = { skipping = job },
                            onRestore = {
                                act(job.id) {
                                    graph.opportunities.transition(sub, job.id, setOf(OpportunityStatus.SKIPPED), OpportunityStatus.PROPOSED, mapOf("skip_reason" to null))
                                    "Back under To review."
                                }
                            },
                            onRetry = {
                                act(job.id) {
                                    graph.opportunities.transition(sub, job.id, setOf(OpportunityStatus.FAILED), OpportunityStatus.CAPTURED)
                                    "Queued again for the desktop's next run."
                                }
                            },
                            onFetch = {
                                act(job.id) {
                                    val page = JobPageFetcher.fetch(job.url)
                                    graph.opportunities.attachCapture(sub, job.id, page.text, via = "share_url").message
                                }
                            },
                            onPaste = { pasting = job },
                            onOpen = { requestOpen(job) },
                            onReload = { replacing = job },
                            onOpenLink = {
                                runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(job.url))) }
                                    .onFailure { error = "Could not open the link: ${it.message}" }
                            },
                        )
                    }
                }
            }
        }
    }

    if (adding) {
        TextDialog(
            title = "Add a job",
            hint = "Posting text or link",
            confirm = "Send to the desktop",
            onDismiss = { adding = false },
            onConfirm = { text ->
                adding = false
                act("add") { sendToPipeline(graph, text, fetchedUrl = "", vendors = emptyList()) }
            },
        )
    }
    pasting?.let { job ->
        TextDialog(
            title = "Posting text",
            hint = "Paste the full job posting",
            confirm = "Save",
            onDismiss = { pasting = null },
            onConfirm = { text ->
                pasting = null
                act(job.id) { graph.opportunities.attachCapture(sub, job.id, text, via = "share_text").message }
            },
        )
    }
    skipping?.let { job ->
        SkipDialog(
            onDismiss = { skipping = null },
            onSkip = { reason ->
                skipping = null
                act(job.id) {
                    graph.opportunities.transition(sub, job.id, SKIPPABLE, OpportunityStatus.SKIPPED, mapOf("skip_reason" to reason))
                    "Skipped."
                }
            },
        )
    }
    replacing?.let { job ->
        val reload = session?.opportunityId == job.id
        AlertDialog(
            onDismissRequest = { replacing = null },
            title = { Text(if (reload) "Reload the drafts?" else "Replace the letter in progress?") },
            text = {
                Text(
                    if (reload) "Your answers and edits to this job on the phone are replaced by the drafts stored by the desktop."
                    else "Opening these drafts replaces the letter in progress on this phone. Letters already saved to Previous examples stay.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    replacing = null
                    open(job)
                }) { Text(if (reload) "Reload" else "Replace") }
            },
            dismissButton = { TextButton(onClick = { replacing = null }) { Text("Cancel") } },
        )
    }
}

private fun emptyText(tab: PipelineTab): String = when (tab) {
    PipelineTab.REVIEW -> "No proposals. The desktop proposes jobs from your job-alert mail."
    PipelineTab.NEEDS_TEXT -> "No approved job is waiting for its posting text."
    PipelineTab.QUEUED -> "Nothing waits for the desktop."
    PipelineTab.RUNNING -> "The desktop is not drafting anything right now."
    PipelineTab.READY -> "No drafts are ready yet."
    PipelineTab.FAILED -> "Nothing failed."
    PipelineTab.ARCHIVE -> "No finished or skipped jobs."
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun JobCard(
    job: Opportunity,
    busy: Boolean,
    isCurrentLetter: Boolean,
    onApprove: () -> Unit,
    onSkip: () -> Unit,
    onRestore: () -> Unit,
    onRetry: () -> Unit,
    onFetch: () -> Unit,
    onPaste: () -> Unit,
    onOpen: () -> Unit,
    onReload: () -> Unit,
    onOpenLink: () -> Unit,
) {
    SectionCard(job.displayTitle) {
        val where = listOf(job.company, job.location, job.source.takeIf { it.isNotEmpty() && it != "manual" }.orEmpty())
            .filter { it.isNotBlank() }
        if (where.isNotEmpty()) Text(where.joinToString(" · "), style = MaterialTheme.typography.bodyMedium)
        Text(statusLine(job), style = MaterialTheme.typography.bodySmall)
        if (job.status == OpportunityStatus.PROPOSED && job.historyNote.isNotEmpty()) {
            Text(job.historyNote, style = MaterialTheme.typography.bodySmall)
        }
        if (job.outcomeLine.isNotEmpty()) {
            Text("Outcome: ${job.outcomeLine}", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
            job.feedbackQuotes.forEach { Text("“$it”", style = MaterialTheme.typography.bodySmall) }
        }
        if (busy) BusyRow("Working")

        when (job.status) {
            OpportunityStatus.READY, OpportunityStatus.DONE, OpportunityStatus.APPLIED -> ReadyDetails(job)
            OpportunityStatus.FAILED -> WarningList(
                job.vendorsFailed.map { (v, e) -> "${PipelineSession.label(v)}: $e" }
                    .ifEmpty { listOf("The desktop could not draft this job.") },
            )
            OpportunityStatus.SKIPPED -> if (job.skipReason.isNotEmpty()) Text("Reason: ${job.skipReason}", style = MaterialTheme.typography.bodySmall)
            else -> Unit
        }
        if (job.vendorsRequested.isNotEmpty() && job.status in setOf(OpportunityStatus.CAPTURED, OpportunityStatus.DRAFTING)) {
            Text("Vendors: ${job.vendorsRequested.joinToString(", ") { PipelineSession.label(it) }}", style = MaterialTheme.typography.bodySmall)
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val enabled = !busy
            if (job.url.isNotEmpty()) TextButton(enabled = enabled, onClick = onOpenLink) { Text("Open posting") }
            when (job.status) {
                OpportunityStatus.PROPOSED -> {
                    Button(enabled = enabled, onClick = onApprove) { Text("Approve") }
                    TextButton(enabled = enabled, onClick = onSkip) { Text("Skip") }
                }
                OpportunityStatus.APPROVED -> {
                    if (job.url.isNotEmpty()) OutlinedButton(enabled = enabled, onClick = onFetch) { Text("Fetch the posting") }
                    OutlinedButton(enabled = enabled, onClick = onPaste) { Text("Paste text") }
                    TextButton(enabled = enabled, onClick = onSkip) { Text("Skip") }
                }
                OpportunityStatus.CAPTURED -> {
                    TextButton(enabled = enabled, onClick = onPaste) { Text("Replace text") }
                    TextButton(enabled = enabled, onClick = onSkip) { Text("Skip") }
                }
                OpportunityStatus.FAILED -> {
                    Button(enabled = enabled, onClick = onRetry) { Text("Retry") }
                    TextButton(enabled = enabled, onClick = onSkip) { Text("Skip") }
                }
                OpportunityStatus.READY, OpportunityStatus.DONE, OpportunityStatus.APPLIED -> {
                    // Applications known only from mail have no drafts to open.
                    val hasDrafts = job.status == OpportunityStatus.READY || job.vendorsDone.isNotEmpty() || isCurrentLetter
                    if (hasDrafts) Button(enabled = enabled, onClick = onOpen) { Text(if (isCurrentLetter) "Go to the letter" else "Open the drafts") }
                    if (isCurrentLetter) TextButton(enabled = enabled, onClick = onReload) { Text("Reload from the desktop") }
                    if (job.status == OpportunityStatus.READY) TextButton(enabled = enabled, onClick = onSkip) { Text("Skip") }
                }
                OpportunityStatus.SKIPPED -> TextButton(enabled = enabled, onClick = onRestore) { Text("Restore") }
                OpportunityStatus.DRAFTING, OpportunityStatus.UNKNOWN -> Unit
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ReadyDetails(job: Opportunity) {
    if (job.vendorsDone.isNotEmpty()) {
        Text("Drafts: ${job.vendorsDone.joinToString(", ") { PipelineSession.label(it) }}", style = MaterialTheme.typography.bodyMedium)
    }
    if (job.inputNeededCount > 0) {
        Text("${job.inputNeededCount} question(s) need your answer.", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
    }
    if (job.fitMatched.isNotEmpty()) Text("Matches: ${job.fitMatched.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
    if (job.fitGaps.isNotEmpty()) Text("Gaps: ${job.fitGaps.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
    val costs = listOfNotNull(
        job.costApiUsd?.let { "API ${formatDollars(it)}" },
        job.costSubscriptionUsd?.let { "subscription ≈ ${formatDollars(it)}" },
    )
    if (costs.isNotEmpty()) Text("Cost: ${costs.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
    if (job.vendorsFailed.isNotEmpty()) {
        WarningList(job.vendorsFailed.map { (v, e) -> "${PipelineSession.label(v)} failed: $e" })
    }
}

private fun statusLine(job: Opportunity): String {
    val what = when (job.status) {
        OpportunityStatus.PROPOSED -> "Proposed from a job alert"
        OpportunityStatus.APPROVED -> "Approved, waiting for the posting text"
        OpportunityStatus.CAPTURED -> "Waiting for the desktop's next run"
        OpportunityStatus.DRAFTING -> listOf("Running on the desktop", job.progressLine).filter { it.isNotEmpty() }.joinToString(" · ")
        OpportunityStatus.READY -> "Drafts ready"
        OpportunityStatus.FAILED -> "Drafting failed"
        OpportunityStatus.DONE -> "Letter saved"
        OpportunityStatus.APPLIED -> "Applied"
        OpportunityStatus.SKIPPED -> "Skipped"
        OpportunityStatus.UNKNOWN -> "Status '${job.statusText}'"
    }
    if (job.status == OpportunityStatus.DRAFTING) {
        // The claim set updated_at; progress reports don't move it.
        val since = formatTime(job.runningSince.ifEmpty { job.updatedAt })
        return if (since.isEmpty()) what else "$what · since $since"
    }
    val at = formatTime(job.updatedAt.ifEmpty { job.createdAt })
    return if (at.isEmpty()) what else "$what · $at"
}

private val TIME_FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("d MMM, HH:mm")

/** ISO time in the phone's zone; a timestamp without a zone (as Python may write) is shown as stored. */
private fun formatTime(iso: String): String {
    if (iso.isEmpty()) return ""
    return runCatching { TIME_FORMAT.format(Instant.parse(iso).atZone(ZoneId.systemDefault())) }
        .getOrElse { iso.take(16).replace('T', ' ') }
}

@Composable
private fun TextDialog(title: String, hint: String, confirm: String, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(value = text, onValueChange = { text = it }, label = { Text(hint) }, minLines = 4, maxLines = 10, modifier = Modifier.fillMaxWidth())
        },
        confirmButton = { TextButton(enabled = text.isNotBlank(), onClick = { onConfirm(text) }) { Text(confirm) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SkipDialog(onDismiss: () -> Unit, onSkip: (String) -> Unit) {
    var reason by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Skip this job?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (r in SKIP_REASONS) FilterChip(selected = reason == r, onClick = { reason = r }, label = { Text(r) })
                }
                OutlinedTextField(value = reason, onValueChange = { reason = it }, label = { Text("Reason (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { TextButton(onClick = { onSkip(reason.trim()) }) { Text("Skip") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
