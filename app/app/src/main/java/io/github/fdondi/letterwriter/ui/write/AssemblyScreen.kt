package io.github.fdondi.letterwriter.ui.write

import android.content.ClipData
import android.content.Intent
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
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
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.pipeline.Translation
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.pipeline.VendorStage
import io.github.fdondi.letterwriter.pipeline.WorkSession
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.PersistedTextField
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import kotlinx.coroutines.launch

/** Pages of the Final tab: the vendor letters, the letter being built, and the info about the job. */
object FinalPage {
    const val LETTERS = 0
    const val YOUR_LETTER = 1
    const val INFO = 2
    val LABELS = listOf("Letters", "Your letter", "Info")
}

/**
 * The final letter. One level of swipeable tabs holds the vendor letters to review, the letter
 * being built and the job info; the vendor letters themselves are swipeable tabs, one per page,
 * so they sit side by side instead of stacked in one scroll.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun AssemblyScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val session by graph.flow.session.collectAsState()
    val s = session ?: return
    val pager = rememberPagerState { FinalPage.LABELS.size }
    val scope = rememberCoroutineScope()
    Column(modifier.fillMaxSize()) {
        PrimaryScrollableTabRow(selectedTabIndex = pager.currentPage.coerceIn(0, FinalPage.LABELS.size - 1), edgePadding = 8.dp) {
            FinalPage.LABELS.forEachIndexed { idx, label ->
                Tab(
                    selected = pager.currentPage == idx,
                    onClick = { scope.launch { pager.animateScrollToPage(idx) } },
                    text = { Text(label) },
                )
            }
        }
        HorizontalPager(state = pager, modifier = Modifier.fillMaxSize(), beyondViewportPageCount = 1) { page ->
            when (page) {
                FinalPage.LETTERS -> LettersPage(graph, s)
                FinalPage.YOUR_LETTER -> YourLetterPage(graph, s)
                else -> InfoPage(s)
            }
        }
    }
}

/**
 * The vendor letters, one swipeable tab per letter. Each letter gets a page of its own, so going
 * from one letter to the other is a lateral swipe instead of scrolling through a list.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun LettersPage(graph: AppGraph, s: WorkSession) {
    val running by graph.flow.running.collectAsState()
    // Letters to review: every finished one, and for desktop jobs also drafts it left unrewritten (0 rounds).
    val finished = s.vendors.mapNotNull { v ->
        s.vendorWork(v).takeIf { w -> w.reviewText.isNotBlank() && (w.stage == VendorStage.FINAL || s.opportunityId != null) }
    }
    if (finished.isEmpty()) {
        Text(
            "No vendor has a finished letter yet. Approve a draft on the Letters tab first.",
            Modifier.padding(16.dp),
            style = MaterialTheme.typography.bodyMedium,
        )
        return
    }
    val pager = rememberPagerState { finished.size }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize()) {
        PrimaryScrollableTabRow(selectedTabIndex = pager.currentPage.coerceIn(0, finished.size - 1), edgePadding = 8.dp) {
            finished.forEachIndexed { idx, w ->
                Tab(
                    selected = pager.currentPage == idx,
                    onClick = { scope.launch { pager.animateScrollToPage(idx) } },
                    text = { Text(vendorLabel(w.vendor)) },
                )
            }
        }
        HorizontalPager(state = pager, modifier = Modifier.fillMaxSize(), beyondViewportPageCount = 1) { page ->
            val w = finished[page]
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
                VendorParagraphReview(graph, s, w, running)
            }
        }
    }
}

/** The letter being built: paragraphs picked from the vendor letters, then copy, share, translate or save. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun YourLetterPage(graph: AppGraph, s: WorkSession) {
    val profile by graph.profiles.profile.collectAsState()
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

    fun copy(text: String) = scope.launch { runCatching { clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Letter", text))) } }
    fun share(text: String) {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
            putExtra(Intent.EXTRA_SUBJECT, listOf(s.intake.jobTitle, s.intake.companyName).filter { it.isNotBlank() }.joinToString(" — "))
        }
        runCatching { context.startActivity(Intent.createChooser(send, "Share the letter")) }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SectionCard("Your letter") {
            if (s.paragraphs.isEmpty()) Text("Add paragraphs from the letters on the Letters page.", style = MaterialTheme.typography.bodySmall)
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
                if (s.documentId != null) {
                    Text("Already saved; saving again updates the same example.", style = MaterialTheme.typography.bodySmall)
                }
                if (s.opportunityId != null) {
                    Text("Saving also marks this job done in the job pipeline.", style = MaterialTheme.typography.bodySmall)
                }
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
