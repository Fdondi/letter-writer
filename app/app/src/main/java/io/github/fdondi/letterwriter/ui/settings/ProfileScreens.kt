package io.github.fdondi.letterwriter.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.asArrayOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.textOrEmpty
import io.github.fdondi.letterwriter.data.InstructionKind
import io.github.fdondi.letterwriter.data.StoredDocument
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import kotlinx.coroutines.launch

/** Runs a profile write, reloads the profile, and reports the outcome in [status]. */
private class SaveState {
    var busy by mutableStateOf(false)
    var status by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)
}

@Composable
private fun rememberSaver(): SaveState = remember { SaveState() }

private suspend fun SaveState.run(graph: AppGraph, done: String, block: suspend (String) -> Unit) {
    busy = true
    status = null
    error = null
    try {
        val sub = graph.auth.requireUser().sub
        block(sub)
        graph.profiles.load(sub)
        status = done
    } catch (e: Exception) {
        error = VendorFlowEngine.describe(e)
    } finally {
        busy = false
    }
}

@Composable
private fun SaveFeedback(state: SaveState) {
    if (state.busy) BusyRow("Saving")
    state.status?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    ErrorText(state.error)
}

@Composable
fun CvScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val profile by graph.profiles.profile.collectAsState()
    val p = profile ?: return
    val scope = rememberCoroutineScope()
    val save = rememberSaver()
    var text by remember(p.baseCv) { mutableStateOf(p.baseCv) }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("${p.cvRevisions.size} saved revision(s). Saving adds a new revision, like the desktop.", style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(value = text, onValueChange = { text = it }, label = { Text("CV") }, modifier = Modifier.fillMaxWidth(), minLines = 12)
        Button(enabled = !save.busy && text.isNotBlank() && text != p.baseCv, onClick = {
            scope.launch { save.run(graph, "CV saved.") { sub -> graph.profiles.appendCvRevision(sub, text) } }
        }) { Text("Save CV") }
        SaveFeedback(save)

        val extra = p.extraInfo
        SectionCard("Notes added to the CV (${extra.size})") {
            if (extra.isEmpty()) Text("Answers you chose to add to the CV during feedback appear here.", style = MaterialTheme.typography.bodySmall)
            for (row in extra) {
                val src = row.textOrEmpty("source").ifEmpty { "manual" }
                val body = listOf("user_context", "user_instructions", "manual_text", "observation")
                    .map { row.textOrEmpty(it).trim() }.filter { it.isNotEmpty() }
                    .plus(row["context_lines"].asArrayOrNull().orEmpty().mapNotNull { it.asStringOrNull() })
                    .joinToString("\n")
                Row(verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        Text("${row.textOrEmpty("category").ifEmpty { src }} · $src", style = MaterialTheme.typography.labelSmall)
                        Text(body, style = MaterialTheme.typography.bodySmall)
                    }
                    TextButton(enabled = !save.busy, onClick = {
                        scope.launch { save.run(graph, "Note removed.") { sub -> graph.profiles.saveExtraInfo(sub, extra.filter { it !== row }) } }
                    }) { Text("Remove") }
                }
            }
        }
    }
}

@Composable
fun ExamplesScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var reload by remember { mutableIntStateOf(0) }
    var docs by remember { mutableStateOf<List<StoredDocument>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var open by remember { mutableStateOf<StoredDocument?>(null) }
    var confirmDelete by remember { mutableStateOf<StoredDocument?>(null) }

    LaunchedEffect(reload) {
        error = null
        docs = try {
            graph.documents.list(graph.auth.requireUser().sub, limit = 200)
        } catch (e: Exception) {
            error = "Could not load previous examples: ${VendorFlowEngine.describe(e)}"
            null
        }
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ErrorText(error)
        val list = docs
        if (list == null && error == null) BusyRow("Loading")
        if (list != null && list.isEmpty()) Text("No saved letters yet.", style = MaterialTheme.typography.bodyMedium)
        for (d in list.orEmpty()) {
            Column(Modifier.fillMaxWidth().clickable { open = d }.padding(vertical = 8.dp)) {
                Text(listOf(d.companyDisplay, d.text("role")).filter { it.isNotBlank() }.joinToString(" — ").ifBlank { "Untitled" }, fontWeight = FontWeight.Medium)
                Text(d.text("created_at").take(10), style = MaterialTheme.typography.bodySmall)
            }
        }
    }

    open?.let { d ->
        AlertDialog(
            onDismissRequest = { open = null },
            title = { Text(d.companyDisplay.ifBlank { "Letter" }) },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Letter", style = MaterialTheme.typography.titleSmall)
                    Text(d.text("letter_text").ifBlank { "(no letter text)" }, style = MaterialTheme.typography.bodySmall)
                    Text("Job offer", style = MaterialTheme.typography.titleSmall)
                    Text(d.text("job_text"), style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton(onClick = { open = null }) { Text("Close") } },
            dismissButton = {
                TextButton(onClick = {
                    confirmDelete = d
                    open = null
                }) { Text("Delete") }
            },
        )
    }
    confirmDelete?.let { d ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Delete this example?") },
            text = { Text("It will no longer be used as an example for new letters, on the phone or the desktop.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = null
                    scope.launch {
                        try {
                            graph.documents.delete(graph.auth.requireUser().sub, d.id)
                        } catch (e: Exception) {
                            error = "Could not delete: ${VendorFlowEngine.describe(e)}"
                        }
                        reload++
                    }
                }) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Cancel") } },
        )
    }
}

@Composable
fun InstructionsScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val profile by graph.profiles.profile.collectAsState()
    val p = profile ?: return
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        for (kind in InstructionKind.entries) InstructionEditor(graph, kind, p)
    }
}

@Composable
private fun InstructionEditor(graph: AppGraph, kind: InstructionKind, profile: io.github.fdondi.letterwriter.data.UserProfile) {
    val state = graph.profiles.instructionState(profile, kind)
    val scope = rememberCoroutineScope()
    val save = rememberSaver()
    var text by remember(state.effective) { mutableStateOf(state.effective) }
    var showDefault by remember { mutableStateOf(false) }
    val title = when (kind) {
        InstructionKind.STYLE -> "Style"
        InstructionKind.STRUCTURE -> "Structure"
        InstructionKind.SEARCH -> "Company research"
    }
    SectionCard(title) {
        Text(if (state.custom != null) "Your custom instructions." else "Using the default instructions.", style = MaterialTheme.typography.bodySmall)
        if (state.upstreamUpdated) WarningList(listOf("The default instructions changed since you customized them. Compare with the default below."))
        OutlinedTextField(value = text, onValueChange = { text = it }, modifier = Modifier.fillMaxWidth(), minLines = 6, maxLines = 24)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !save.busy && text.isNotBlank() && text != state.effective, onClick = {
                scope.launch { save.run(graph, "Saved.") { sub -> graph.profiles.saveInstruction(sub, kind, text) } }
            }) { Text("Save") }
            if (state.custom != null) OutlinedButton(enabled = !save.busy, onClick = {
                scope.launch { save.run(graph, "Back to the default.") { sub -> graph.profiles.clearInstruction(sub, kind) } }
            }) { Text("Use default") }
            TextButton(onClick = { showDefault = !showDefault }) { Text(if (showDefault) "Hide default" else "Show default") }
        }
        if (showDefault) Text(state.default, style = MaterialTheme.typography.bodySmall)
        SaveFeedback(save)
    }
}
