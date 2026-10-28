package io.github.fdondi.letterwriter.ui.intake

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.pyStr
import androidx.core.content.ContextCompat
import io.github.fdondi.letterwriter.data.CaptureRequest
import io.github.fdondi.letterwriter.data.JobPageFetcher
import io.github.fdondi.letterwriter.llm.ClientFactory
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.pipeline.JobIntake
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.pipeline.VendorStage
import io.github.fdondi.letterwriter.pipeline.WorkSession
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.PersistedTextField
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import io.github.fdondi.letterwriter.ui.common.formatDollars
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

@Composable
fun IntakeScreen(graph: AppGraph, onStartWriting: () -> Unit, onSentToPipeline: () -> Unit, modifier: Modifier = Modifier) {
    val session by graph.flow.session.collectAsState()
    val loaded by graph.flow.loaded.collectAsState()
    val shared by graph.incomingShare.collectAsState()
    val corruption by graph.workSessions.corruption.collectAsState()
    var pendingShare by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(shared, session, loaded) {
        val text = shared ?: return@LaunchedEffect
        if (!loaded) return@LaunchedEffect
        if (session != null) pendingShare = text
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        corruption?.let {
            ErrorText(it)
            TextButton(onClick = { graph.workSessions.dismissCorruption() }) { Text("Dismiss") }
        }
        val s = session
        when {
            !loaded -> BusyRow("Loading the letter in progress")
            s == null -> NewLetterForm(
                graph,
                initialText = shared.orEmpty(),
                onConsumedShare = { graph.incomingShare.value = null },
                onSentToPipeline = onSentToPipeline,
            )
            else -> JobDetails(graph, s, onStartWriting)
        }
    }

    pendingShare?.let { text ->
        AlertDialog(
            onDismissRequest = {
                pendingShare = null
                graph.incomingShare.value = null
            },
            title = { Text("Start a new letter?") },
            text = {
                Text(
                    "You shared a job post, but a letter is already in progress. Starting a new one discards the current letter. " +
                        "Sending it to the desktop keeps the current letter; the desktop drafts the new job on its next run.",
                )
            },
            confirmButton = {
                Column(horizontalAlignment = Alignment.End) {
                    TextButton(onClick = {
                        pendingShare = null
                        graph.incomingShare.value = null
                        scope.launch {
                            val result = sendToPipeline(graph, text, fetchedUrl = "", vendors = emptyList())
                            graph.flow.showMessage(result)
                        }
                    }) { Text("Send to the desktop") }
                    TextButton(onClick = {
                        pendingShare = null
                        graph.flow.discardSession()
                    }) { Text("Discard and start new") }
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    pendingShare = null
                    graph.incomingShare.value = null
                }) { Text("Keep current") }
            },
        )
    }
}

private fun keyedVendors(graph: AppGraph): List<ModelVendor> =
    ModelVendor.entries.filter { graph.apiKeys.value.has(ClientFactory.keyField(it)) }

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VendorPicker(graph: AppGraph, selected: List<String>, onChange: (List<String>) -> Unit, enabled: Boolean = true) {
    val keyed = keyedVendors(graph).map { it.key }.toSet()
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for (v in ModelVendor.entries) {
            val has = v.key in keyed
            FilterChip(
                selected = v.key in selected,
                enabled = enabled && has,
                onClick = { onChange(if (v.key in selected) selected - v.key else selected + v.key) },
                label = { Text(if (has) v.label else "${v.label} (no key)") },
            )
        }
    }
}

/**
 * Puts the posting in the desktop pipeline (`opportunities`): text becomes a `captured` job, a bare link an
 * `approved` one that waits for its text. [fetchedUrl] is set when [text] was downloaded from that link.
 * Returns the line to show the user; never throws.
 */
suspend fun sendToPipeline(
    graph: AppGraph,
    text: String,
    fetchedUrl: String,
    vendors: List<String>,
    rewriteRounds: Int? = null,
    finalFeedback: Boolean? = null,
): String =
    try {
        val linkOnly = if (fetchedUrl.isEmpty()) JobPageFetcher.urlIn(text) else null
        val base = CaptureRequest(text = text.trim(), url = "", via = "share_text", vendorsRequested = vendors, rewriteRounds = rewriteRounds, finalFeedback = finalFeedback)
        val request = when {
            fetchedUrl.isNotEmpty() -> base.copy(url = fetchedUrl, via = "share_url")
            linkOnly != null -> base.copy(text = "", url = linkOnly, via = "share_url")
            // Links inside a pasted posting (company site, apply page) don't identify the job; the text does.
            else -> base
        }
        graph.opportunities.capture(graph.auth.requireUser().sub, request).message
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        "Could not send the job to the desktop: ${VendorFlowEngine.describe(e)}"
    }

/**
 * Every vendor a new letter can use: the API vendors and the desktop's local model. Anthropic is one
 * vendor run two ways: through its API when drafting here, as Claude Code (the subscription) on the desktop.
 */
private val ALL_VENDORS: List<Pair<String, String>> =
    ModelVendor.entries.map { it.key to it.label } + ("local" to "Local model")

/** The vendor names the desktop batch runs: Anthropic there is Claude Code. */
private fun forDesktop(vendors: List<String>): List<String> =
    vendors.map { if (it == ModelVendor.ANTHROPIC.key) "claude_code" else it }.distinct()

@Composable
private fun NewLetterForm(graph: AppGraph, initialText: String, onConsumedShare: () -> Unit, onSentToPipeline: () -> Unit) {
    val profile by graph.profiles.profile.collectAsState()
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf(initialText) }
    var sourceUrl by remember { mutableStateOf("") }
    var fetching by remember { mutableStateOf(false) }
    var fetchError by remember { mutableStateOf<String?>(null) }
    val keyed = keyedVendors(graph).map { it.key }
    // One choice for both buttons: drafting here uses the picked vendors with a key on this phone,
    // the desktop gets all of them (it has its own keys, and Claude Code runs only there).
    // Every vendor starts selected; untick the ones you don't want.
    var vendors by remember { mutableStateOf(ALL_VENDORS.map { it.first }) }
    val here = vendors.filter { it in keyed }
    var includePlan by remember { mutableStateOf(true) }
    var rewriteRounds by remember { mutableIntStateOf(1) }
    var finalFeedback by remember { mutableStateOf(true) }
    var sending by remember { mutableStateOf(false) }

    LaunchedEffect(initialText) {
        if (initialText.isNotBlank()) {
            text = initialText
            onConsumedShare()
        }
    }

    Text("New letter", style = MaterialTheme.typography.headlineSmall)
    OutlinedTextField(
        value = text,
        onValueChange = { text = it },
        label = { Text("Job offer text or link") },
        modifier = Modifier.fillMaxWidth(),
        minLines = 8,
        maxLines = 16,
    )
    val url = JobPageFetcher.urlIn(text)
    if (url != null) {
        if (fetching) {
            BusyRow("Downloading the job page")
        } else {
            OutlinedButton(onClick = {
                fetching = true
                fetchError = null
                scope.launch {
                    try {
                        val page = JobPageFetcher.fetch(url)
                        text = page.text
                        sourceUrl = page.url
                    } catch (e: Exception) {
                        fetchError = "Could not read the job page: ${e.message}"
                    } finally {
                        fetching = false
                    }
                }
            }) { Text("Fetch the job page") }
        }
    }
    ErrorText(fetchError)
    if (sourceUrl.isNotEmpty()) Text("Text downloaded from $sourceUrl — check it before starting.", style = MaterialTheme.typography.bodySmall)

    Text("Vendors", style = MaterialTheme.typography.titleSmall)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for ((key, label) in ALL_VENDORS) {
            FilterChip(
                selected = key in vendors,
                onClick = { vendors = if (key in vendors) vendors - key else vendors + key },
                label = { Text(if (key in keyed) label else "$label · desktop only") },
            )
        }
    }
    Text("Anthropic drafts with its API here and as Claude Code (your subscription) on the desktop.", style = MaterialTheme.typography.bodySmall)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked = includePlan, onCheckedChange = { includePlan = it })
        Text("  Plan each letter before drafting")
    }
    Text("On the desktop", style = MaterialTheme.typography.titleSmall)
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Comment and rewrite")
        for (n in 0..2) {
            FilterChip(selected = rewriteRounds == n, onClick = { rewriteRounds = n }, label = { Text(if (n == 1) "1×" else "$n×") })
        }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked = finalFeedback, onCheckedChange = { finalFeedback = it })
        Text("  Comment the last version")
    }
    Text(
        when {
            rewriteRounds == 0 && finalFeedback -> "You get each draft with its comments on the paragraphs."
            rewriteRounds == 0 -> "You get each draft as it is, without comments."
            finalFeedback -> "Each draft is commented and rewritten ${if (rewriteRounds == 1) "once" else "twice"}, then the result is commented for you."
            else -> "Each draft is commented and rewritten ${if (rewriteRounds == 1) "once" else "twice"}; you get the result as it is."
        },
        style = MaterialTheme.typography.bodySmall,
    )
    if (sending) {
        BusyRow("Saving to the job pipeline")
    } else {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                enabled = text.isNotBlank() && url == null && here.isNotEmpty() && !fetching,
                onClick = { graph.flow.startLetter(text, sourceUrl, here, includePlan) },
                modifier = Modifier.weight(1f),
            ) { Text("Draft here") }
            OutlinedButton(
                enabled = text.isNotBlank() && vendors.isNotEmpty() && !fetching,
                onClick = {
                    sending = true
                    scope.launch {
                        val result = sendToPipeline(graph, text, sourceUrl, forDesktop(vendors), rewriteRounds, finalFeedback)
                        sending = false
                        graph.flow.showMessage(result)
                        if (!result.startsWith("Could not")) {
                            text = ""
                            sourceUrl = ""
                            onSentToPipeline()
                        }
                    }
                },
                modifier = Modifier.weight(1f),
            ) { Text("Send to the desktop") }
        }
    }
    Text(
        when {
            url != null -> "Draft here needs the posting text: fetch the page or paste it. The desktop takes a bare link; it waits under Job pipeline → Needs text."
            here.isEmpty() -> "None of the picked vendors has an API key on this phone, so only the desktop can draft. Add keys in Settings → API keys."
            else -> "Draft here writes now on this phone. Send to the desktop drafts on its next run; open the result under Job pipeline → Ready."
        },
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun JobDetails(graph: AppGraph, s: WorkSession, onStartWriting: () -> Unit) {
    val running by graph.flow.running.collectAsState()
    val i = s.intake
    val key = s.sessionId
    var confirmDiscard by remember { mutableStateOf(false) }
    fun update(f: (JobIntake) -> JobIntake) = graph.flow.updateIntake(f)

    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(i.companyName.ifBlank { "Untitled job" }, style = MaterialTheme.typography.headlineSmall)
            if (i.jobTitle.isNotBlank()) Text(i.jobTitle, style = MaterialTheme.typography.bodyLarge)
        }
        TextButton(onClick = { confirmDiscard = true }) { Text("New letter") }
    }
    val intakeCost = i.costs.values.sum()
    if (intakeCost > 0) Text("Spent on reading and research: ${formatDollars(intakeCost)}", style = MaterialTheme.typography.bodySmall)

    running["extract"]?.let { BusyRow(it) }
    WarningList(i.warnings)

    SectionCard("Job offer") {
        PersistedTextField(i.jobText, { t -> update { it.copy(jobText = t) } }, "Job offer text", key = key, minLines = 5, maxLines = 12)
        OutlinedButton(enabled = "extract" !in running, onClick = { graph.flow.extract() }) {
            Text(if (i.extracted) "Read it again" else "Read the job offer")
        }
    }

    SectionCard("Details") {
        PersistedTextField(i.companyName, { t -> update { it.copy(companyName = t) } }, "Company", key = key, singleLine = true)
        PersistedTextField(i.jobTitle, { t -> update { it.copy(jobTitle = t) } }, "Job title", key = key, singleLine = true)
        PersistedTextField(i.location, { t -> update { it.copy(location = t) } }, "Location", key = key, singleLine = true)
        PersistedTextField(i.language, { t -> update { it.copy(language = t) } }, "Letter language", key = key, singleLine = true)
        PersistedTextField(i.salary, { t -> update { it.copy(salary = t) } }, "Salary", key = key, singleLine = true)
        PersistedTextField(i.sourceUrl, { t -> update { it.copy(sourceUrl = t) } }, "Source URL", key = key, singleLine = true)
        val pocName = i.pointOfContact?.get("name").asStringOrNull().orEmpty()
        PersistedTextField(pocName, { t -> update { it.copy(pointOfContact = withPocName(it.pointOfContact, t)) } }, "Point of contact", key = key, singleLine = true)
        i.pointOfContact?.let { poc ->
            val extra = listOf("role", "contact_details", "notes").mapNotNull { k -> poc[k].asStringOrNull()?.takeIf { it.isNotBlank() } }
            if (extra.isNotEmpty()) Text(extra.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
        }
        PersistedTextField(i.hireProblem, { t -> update { it.copy(hireProblem = t) } }, "What problem this hire solves", key = key, minLines = 2)
    }

    if (i.competences.isNotEmpty()) {
        SectionCard("Key competences") {
            for ((skill, v) in i.competences) {
                val o = v.asObjectOrNull()
                Row(Modifier.fillMaxWidth()) {
                    Text(skill, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                    Text("${o?.get("need").pyStr()} · ${o?.get("level").pyStr()}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }

    SectionCard("Similar letters used as examples") {
        if (i.similarDocuments.isEmpty()) {
            Text(if (i.extracted) "No similar saved letters were found." else "Found when the job offer is read.", style = MaterialTheme.typography.bodySmall)
        }
        if (i.decisionDetail.isNotBlank()) Text(i.decisionDetail, style = MaterialTheme.typography.bodySmall)
        for (doc in i.similarDocuments) SimilarDocRow(doc, WorkSession.docKey(doc) in i.selectedDocIds) { graph.flow.toggleDocument(WorkSession.docKey(doc)) }
    }

    SectionCard("Company research") {
        running["research"]?.let { BusyRow(it) }
        OutlinedButton(enabled = "research" !in running && i.companyName.isNotBlank(), onClick = { graph.flow.research() }) {
            Text(if (i.companyReports.isEmpty()) "Research the company" else "Research again")
        }
        if (i.researchSource.isNotEmpty()) {
            Text(
                when (i.researchSource) {
                    "cache" -> "Reused a saved report (less than 6 months old)."
                    "similar" -> "Reused the saved report of a company with a similar name."
                    "fixture" -> "Fixture text from the debug harness. Nothing was fetched or saved."
                    else -> "New research."
                },
                style = MaterialTheme.typography.bodySmall,
            )
        }
        for ((model, v) in i.companyReports) {
            val o = v.asObjectOrNull()
            val err = o?.get("error").asStringOrNull()
            Row(Modifier.fillMaxWidth().clickable(enabled = err == null) { graph.flow.selectReport(model) }, verticalAlignment = Alignment.CenterVertically) {
                RadioButton(selected = i.selectedReportModel == model, enabled = err == null, onClick = { graph.flow.selectReport(model) })
                Text(if (err != null) "$model — failed: $err" else model, style = MaterialTheme.typography.bodyMedium)
            }
        }
        PersistedTextField(i.companyReport, { t -> update { it.copy(companyReport = t) } }, "Company report used by every vendor", key = "$key/${i.selectedReportModel}", minLines = 4, maxLines = 14)
        for ((model, v) in i.pocReports) {
            val o = v.asObjectOrNull()
            Text("Point of contact ($model)", style = MaterialTheme.typography.titleSmall)
            Text(o?.get("report").asStringOrNull() ?: "Failed: ${o?.get("error").pyStr()}", style = MaterialTheme.typography.bodySmall)
        }
    }

    SectionCard("Notes for the model") {
        PersistedTextField(i.additionalUserInfo, { t -> update { it.copy(additionalUserInfo = t) } }, "About you, for this job", key = key, minLines = 2)
        PersistedTextField(i.additionalCompanyInfo, { t -> update { it.copy(additionalCompanyInfo = t) } }, "About the company (used by research)", key = key, minLines = 2)
    }

    val anyStarted = s.work.values.any { it.stage != VendorStage.NOT_STARTED }
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val context = LocalContext.current
    SectionCard("Vendors") {
        VendorPicker(graph, s.vendors, { graph.flow.setVendors(it, s.includePlanStep) })
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = s.includePlanStep, onCheckedChange = { graph.flow.setVendors(s.vendors, it) })
            Text("  Plan each letter before drafting")
        }
    }
    if (i.companyReport.isBlank()) Text("No company report yet: letters will be written without one.", style = MaterialTheme.typography.bodySmall)
    Button(
        enabled = s.vendors.isNotEmpty() && i.extracted && "extract" !in running,
        onClick = {
            // The "working" notification keeps drafts alive in the background; it only shows with this permission.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) {
                runCatching { askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS) }
            }
            for (v in s.vendors) if (s.vendorWork(v).stage == VendorStage.NOT_STARTED && "vendor:$v" !in running) graph.flow.startVendor(v)
            onStartWriting()
        },
        modifier = Modifier.fillMaxWidth(),
    ) { Text(if (anyStarted) "Go to the letters" else "Write the letters") }

    if (confirmDiscard) {
        AlertDialog(
            onDismissRequest = { confirmDiscard = false },
            title = { Text("Discard this letter?") },
            text = { Text("The job details, drafts and feedback on this phone are deleted. Letters already saved to Previous examples stay.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDiscard = false
                    graph.flow.discardSession()
                }) { Text("Discard") }
            },
            dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text("Cancel") } },
        )
    }
}

private fun withPocName(poc: JsonObject?, name: String): JsonObject? {
    if (poc == null && name.isBlank()) return null
    return buildJsonObject {
        poc?.forEach { (k, v) -> if (k != "name") put(k, v) }
        put("name", name)
    }
}

@Composable
private fun SimilarDocRow(doc: JsonObject, selected: Boolean, onToggle: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onToggle), verticalAlignment = Alignment.Top) {
        Checkbox(checked = selected, onCheckedChange = { onToggle() })
        Column(Modifier.weight(1f).padding(top = 12.dp)) {
            val company = doc["company_name"].asStringOrNull().orEmpty()
            val role = doc["role"].asStringOrNull().orEmpty()
            val score = doc["score"]?.pyStr()
            Text(listOf(company, role).filter { it.isNotBlank() }.joinToString(" — "), fontWeight = FontWeight.Medium)
            if (score != null) {
                val source = doc["score_source"].asStringOrNull()
                Text("Similarity score $score${if (source == "decision_model") " (decision model)" else ""}", style = MaterialTheme.typography.bodySmall)
            }
            val sims = (doc["similarities"] as? JsonArray).orEmpty().map { it.pyStr() }.filter { it.isNotBlank() }
            if (sims.isNotEmpty()) Text(sims.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
        }
    }
}
