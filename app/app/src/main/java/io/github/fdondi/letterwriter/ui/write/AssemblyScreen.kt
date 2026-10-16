package io.github.fdondi.letterwriter.ui.write

import android.content.ClipData
import android.content.Intent
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.pipeline.Translation
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.pipeline.VendorStage
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.PersistedTextField
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import kotlinx.coroutines.launch

/** Final letter: paragraphs picked from the vendor letters, then copy, share, translate or save. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AssemblyScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val session by graph.flow.session.collectAsState()
    val profile by graph.profiles.profile.collectAsState()
    val s = session ?: return
    val flow = graph.flow
    val context = LocalContext.current
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    var saving by remember { mutableStateOf(false) }
    var saveResult by remember { mutableStateOf<String?>(null) }
    var saveError by remember { mutableStateOf<String?>(null) }
    var translating by remember { mutableStateOf(false) }
    var translation by remember { mutableStateOf<Translation?>(null) }
    var translateError by remember { mutableStateOf<String?>(null) }

    fun copy(text: String) = scope.launch { clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Letter", text))) }
    fun share(text: String) {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
            putExtra(Intent.EXTRA_SUBJECT, listOf(s.intake.jobTitle, s.intake.companyName).filter { it.isNotBlank() }.joinToString(" — "))
        }
        context.startActivity(Intent.createChooser(send, "Share the letter"))
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val finished = s.vendors.mapNotNull { v -> s.vendorWork(v).takeIf { it.stage == VendorStage.FINAL && it.finalLetter.isNotBlank() } }
        if (finished.isEmpty()) {
            Text("No vendor has a finished letter yet. Approve a draft on the Letters tab first.", style = MaterialTheme.typography.bodyMedium)
        }
        for (w in finished) {
            var expanded by remember(w.vendor) { mutableStateOf(s.paragraphs.isEmpty() && finished.size == 1) }
            SectionCard(vendorLabel(w.vendor)) {
                Text(w.finalLetter, style = MaterialTheme.typography.bodyMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { flow.useWholeLetter(w.vendor) }) { Text("Use whole letter") }
                    TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Hide paragraphs" else "Pick paragraphs") }
                }
                if (expanded) {
                    for (p in w.finalLetter.split(Regex("\\n\\s*\\n")).map { it.trim() }.filter { it.isNotEmpty() }) {
                        Row(verticalAlignment = Alignment.Top) {
                            Text(p, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                            TextButton(onClick = { flow.addParagraph(w.vendor, p) }) { Text("Add") }
                        }
                    }
                }
            }
        }

        SectionCard("Your letter") {
            if (s.paragraphs.isEmpty()) Text("Add paragraphs from the letters above.", style = MaterialTheme.typography.bodySmall)
            s.paragraphs.forEachIndexed { idx, p ->
                Text(
                    "${vendorLabel(p.vendor)}${if (p.text != p.originalText) " · edited" else ""}",
                    style = MaterialTheme.typography.labelSmall,
                )
                PersistedTextField(p.text, { flow.updateParagraph(p.id, it) }, "Paragraph ${idx + 1}", key = p.id, minLines = 2)
                Row {
                    IconButton(enabled = idx > 0, onClick = { flow.moveParagraph(p.id, -1) }) { Icon(Icons.Filled.KeyboardArrowUp, "Move up") }
                    IconButton(enabled = idx < s.paragraphs.size - 1, onClick = { flow.moveParagraph(p.id, 1) }) { Icon(Icons.Filled.KeyboardArrowDown, "Move down") }
                    IconButton(onClick = { flow.removeParagraph(p.id) }) { Icon(Icons.Filled.Delete, "Remove") }
                }
            }
        }

        val text = s.finalText
        if (text.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { copy(text) }) { Text("Copy") }
                OutlinedButton(onClick = { share(text) }) { Text("Share") }
            }
            SectionCard("Save to Previous examples") {
                Text(
                    if (s.documentId == null) "Saves the letter, the vendor letters and your ratings, and the answers you chose to remember."
                    else "Already saved; saving again updates the same example.",
                    style = MaterialTheme.typography.bodySmall,
                )
                if (saving) {
                    BusyRow("Saving")
                } else {
                    Button(onClick = {
                        saving = true
                        saveError = null
                        saveResult = null
                        scope.launch {
                            try {
                                flow.saveLetter()
                                saveResult = "Saved."
                            } catch (e: Exception) {
                                saveError = "Failed to save letter: ${VendorFlowEngine.describe(e)}"
                            } finally {
                                saving = false
                            }
                        }
                    }) { Text(if (s.documentId == null) "Save" else "Save again") }
                }
                saveResult?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                ErrorText(saveError)
            }

            SectionCard("Translate") {
                val languages = profile?.let { graph.languages.defaultLanguages(it.data).filter { l -> l.enabled } }.orEmpty()
                if (languages.isEmpty()) Text("No languages are enabled. Add them in Settings → Languages.", style = MaterialTheme.typography.bodySmall)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (l in languages) {
                        FilterChip(
                            selected = false,
                            enabled = !translating,
                            onClick = {
                                translating = true
                                translateError = null
                                scope.launch {
                                    try {
                                        translation = flow.translate(text, l.code)
                                    } catch (e: Exception) {
                                        translateError = "Translation failed: ${VendorFlowEngine.describe(e)}"
                                    } finally {
                                        translating = false
                                    }
                                }
                            },
                            label = { Text(l.label.ifBlank { l.code.uppercase() }) },
                        )
                    }
                }
                if (translating) BusyRow("Translating")
                ErrorText(translateError)
                translation?.let { t ->
                    WarningList(listOfNotNull(t.warning))
                    Text(t.text, style = MaterialTheme.typography.bodyMedium)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { copy(t.text) }) { Text("Copy translation") }
                        OutlinedButton(onClick = { share(t.text) }) { Text("Share translation") }
                    }
                }
            }
        }
    }
}
