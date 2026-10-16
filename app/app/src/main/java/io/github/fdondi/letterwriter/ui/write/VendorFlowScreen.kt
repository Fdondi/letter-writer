package io.github.fdondi.letterwriter.ui.write

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.asStringOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.llm.ModelVendor
import io.github.fdondi.letterwriter.pipeline.FeedbackItems
import io.github.fdondi.letterwriter.pipeline.FeedbackUi
import io.github.fdondi.letterwriter.pipeline.VendorStage
import io.github.fdondi.letterwriter.pipeline.VendorWork
import io.github.fdondi.letterwriter.pipeline.WorkSession
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.PersistedTextField
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import io.github.fdondi.letterwriter.ui.common.formatDollars
import kotlinx.coroutines.launch

val CATEGORY_LABELS = mapOf(
    "instruction" to "Instructions",
    "accuracy" to "CV accuracy",
    "precision" to "Precision",
    "company_fit" to "Company fit",
    "goal_fit" to "Goal fit",
    "user_fit" to "Your voice",
    "human" to "Human",
)

fun vendorLabel(key: String): String = ModelVendor.fromKey(key)?.label ?: key

@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun VendorFlowScreen(graph: AppGraph, onGoToFinal: () -> Unit, modifier: Modifier = Modifier) {
    val session by graph.flow.session.collectAsState()
    val running by graph.flow.running.collectAsState()
    val s = session ?: return
    val vendors = s.vendors
    if (vendors.isEmpty()) {
        Text("Pick at least one vendor on the Job tab.", modifier.padding(16.dp))
        return
    }
    val pager = rememberPagerState { vendors.size }
    val scope = rememberCoroutineScope()
    var showReference by remember { mutableStateOf(false) }

    Column(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PrimaryScrollableTabRow(selectedTabIndex = pager.currentPage.coerceIn(0, vendors.size - 1), modifier = Modifier.weight(1f), edgePadding = 8.dp) {
                vendors.forEachIndexed { idx, v ->
                    Tab(
                        selected = pager.currentPage == idx,
                        onClick = { scope.launch { pager.animateScrollToPage(idx) } },
                        text = {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                StatusDot(s.vendorWork(v), "vendor:$v" in running)
                                Text(vendorLabel(v))
                            }
                        },
                    )
                }
            }
            TextButton(onClick = { showReference = true }) { Text("Job") }
        }
        HorizontalPager(state = pager, modifier = Modifier.fillMaxSize(), beyondViewportPageCount = 1) { page ->
            val v = vendors[page]
            VendorPage(graph, s, v, running["vendor:$v"], onGoToFinal)
        }
    }

    if (showReference) {
        ModalBottomSheet(onDismissRequest = { showReference = false }) {
            ReferenceSheet(s)
        }
    }
}

@Composable
private fun StatusDot(w: VendorWork, busy: Boolean) {
    val color = when {
        w.error != null -> MaterialTheme.colorScheme.error
        busy -> MaterialTheme.colorScheme.tertiary
        w.stage == VendorStage.FINAL -> Color(0xFF2E7D32)
        w.stage == VendorStage.DRAFT && w.allApproved() -> Color(0xFF2E7D32)
        w.stage == VendorStage.NOT_STARTED -> MaterialTheme.colorScheme.outline
        else -> MaterialTheme.colorScheme.primary
    }
    Box(Modifier.size(8.dp).background(color, CircleShape))
}

@Composable
private fun ReferenceSheet(s: WorkSession) {
    val i = s.intake
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(listOf(i.companyName, i.jobTitle).filter { it.isNotBlank() }.joinToString(" — "), style = MaterialTheme.typography.titleLarge)
        if (i.hireProblem.isNotBlank()) {
            Text("Hire goal", style = MaterialTheme.typography.titleSmall)
            Text(i.hireProblem, style = MaterialTheme.typography.bodyMedium)
        }
        if (i.competences.isNotEmpty()) {
            Text("Key competences", style = MaterialTheme.typography.titleSmall)
            for ((skill, v) in i.competences) {
                val o = v.asObjectOrNull()
                Text("$skill — ${o?.get("need").pyStr()} · ${o?.get("level").pyStr()}", style = MaterialTheme.typography.bodySmall)
            }
        }
        if (i.companyReport.isNotBlank()) {
            Text("Company report", style = MaterialTheme.typography.titleSmall)
            Text(i.companyReport, style = MaterialTheme.typography.bodySmall)
        }
        for ((model, v) in i.pocReports) {
            v.asObjectOrNull()?.get("report").asStringOrNull()?.let {
                Text("Point of contact ($model)", style = MaterialTheme.typography.titleSmall)
                Text(it, style = MaterialTheme.typography.bodySmall)
            }
        }
        Text("Job offer", style = MaterialTheme.typography.titleSmall)
        Text(i.jobText, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun VendorPage(graph: AppGraph, s: WorkSession, vendor: String, busy: String?, onGoToFinal: () -> Unit) {
    val w = s.vendorWork(vendor)
    val flow = graph.flow
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(vendorLabel(vendor), style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            if (w.totalCost > 0) Text(formatDollars(w.totalCost), style = MaterialTheme.typography.bodyMedium)
        }
        busy?.let { BusyRow(it) }
        w.error?.let { err ->
            ErrorText(err)
            if (busy == null) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = {
                        when (w.stage) {
                            VendorStage.NOT_STARTED -> flow.startVendor(vendor)
                            VendorStage.PLAN -> if (w.letterPlan.isNotEmpty()) flow.approvePlan(vendor, w.letterPlan) else flow.redoPlan(vendor)
                            VendorStage.DRAFT -> if (w.feedback.isEmpty()) flow.checkDraft(vendor) else flow.refine(vendor, false)
                            VendorStage.FINAL -> flow.refine(vendor, false)
                        }
                    }) { Text("Try again") }
                    TextButton(onClick = { flow.startVendor(vendor) }) { Text("Start over") }
                }
            }
        }
        WarningList(w.warnings)

        if (w.stage == VendorStage.NOT_STARTED && busy == null && w.error == null) {
            Button(onClick = { flow.startVendor(vendor) }) { Text(if (s.includePlanStep) "Plan the letter" else "Write the draft") }
        }

        if (w.letterPlan.isNotEmpty() || w.stage == VendorStage.PLAN) {
            SectionCard("Plan") {
                if (w.stage == VendorStage.PLAN) {
                    PersistedTextField(w.letterPlan, { flow.editPlan(vendor, it) }, "Letter plan", key = "${s.sessionId}/$vendor/plan", minLines = 6, maxLines = 20)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = busy == null, onClick = { flow.approvePlan(vendor, w.letterPlan) }) { Text("Approve and draft") }
                        OutlinedButton(enabled = busy == null, onClick = { flow.redoPlan(vendor) }) { Text("Plan again") }
                    }
                } else {
                    CollapsibleText(w.letterPlan)
                }
            }
        }

        if (w.draftLetter.isNotEmpty()) DraftSection(graph, s, vendor, w, busy)

        if (w.stage == VendorStage.FINAL) {
            SectionCard("Final letter") {
                PersistedTextField(w.finalLetter, { flow.editFinal(vendor, it) }, "Letter", key = "${s.sessionId}/$vendor/final", minLines = 8, maxLines = 40)
                RatingRow(w.rating) { r -> flow.rate(vendor, r, w.comment) }
                PersistedTextField(w.comment, { flow.rate(vendor, w.rating, it) }, "Comment on this vendor's letter", key = "${s.sessionId}/$vendor/comment", singleLine = true)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        flow.useWholeLetter(vendor)
                        onGoToFinal()
                    }) { Text("Use this letter") }
                    OutlinedButton(onClick = onGoToFinal) { Text("Mix paragraphs") }
                }
                OutlinedButton(enabled = busy == null, onClick = { flow.refine(vendor, false) }) { Text("Rewrite again") }
            }
        }
    }
}

@Composable
private fun CollapsibleText(text: String) {
    var expanded by remember { mutableStateOf(false) }
    Text(if (expanded || text.length < 400) text else text.take(400) + "…", style = MaterialTheme.typography.bodySmall)
    if (text.length >= 400) TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Show less" else "Show all") }
}

@Composable
private fun RatingRow(rating: Int?, onRate: (Int?) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("Rating", Modifier.padding(end = 8.dp))
        for (n in 1..5) {
            TextButton(onClick = { onRate(if (rating == n) null else n) }) {
                Text(if (rating != null && n <= rating) "★" else "☆", style = MaterialTheme.typography.titleLarge)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DraftSection(graph: AppGraph, s: WorkSession, vendor: String, w: VendorWork, busy: String?) {
    val flow = graph.flow
    var editing by rememberSaveable(vendor) { mutableStateOf(false) }
    var fancy by rememberSaveable(vendor) { mutableStateOf(false) }
    var category by rememberSaveable(vendor) { mutableStateOf(FeedbackItems.CATEGORIES.first()) }
    val isDraftStage = w.stage == VendorStage.DRAFT

    SectionCard("Draft") {
        val shown = w.draftEdited ?: w.draftLetter
        if (editing && isDraftStage) {
            PersistedTextField(shown, { flow.editDraft(vendor, it) }, "Draft (your edits are used for the rewrite)", key = "${s.sessionId}/$vendor/draft", minLines = 8, maxLines = 40)
        } else if (isDraftStage) {
            Text(shown, style = MaterialTheme.typography.bodyMedium)
        } else {
            CollapsibleText(shown)
        }
        if (isDraftStage) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { editing = !editing }) { Text(if (editing) "Done editing" else "Edit draft") }
                TextButton(enabled = busy == null, onClick = { flow.redoDraft(vendor) }) { Text("Draft again") }
            }
        }
    }

    if (!isDraftStage) return

    if (w.checkErrors.isNotEmpty()) {
        ErrorText(w.checkErrors.entries.joinToString("\n") { (cat, e) -> "${CATEGORY_LABELS[cat] ?: cat}: $e" })
    }

    SectionCard("Feedback") {
        if (w.feedback.isEmpty()) {
            Text(
                if (busy != null) "Feedback appears here when the check finishes."
                else "This draft has no feedback yet.",
                style = MaterialTheme.typography.bodyMedium,
            )
            if (busy == null) {
                Button(onClick = { flow.checkDraft(vendor) }) { Text("Check this draft") }
            }
        } else {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (cat in FeedbackItems.CATEGORIES) {
                    val items = w.items(cat)
                    val pending = FeedbackUi.pleaseFixItems(items).count { !FeedbackUi.itemIsApproved(it, w.itemApprovals) }
                    FilterChip(
                        selected = category == cat,
                        onClick = { category = cat },
                        label = { Text("${CATEGORY_LABELS[cat] ?: cat}${if (pending > 0) " · $pending" else if (items.isNotEmpty()) " ✓" else ""}") },
                    )
                }
            }
            val items = w.items(category)
            val visible = items.filter { !FeedbackUi.isHidden(it) }
            val hidden = items.filter { FeedbackUi.isHidden(it) }
            if (visible.isEmpty()) Text("No comments in this category.", style = MaterialTheme.typography.bodySmall)
            for (item in visible) FeedbackItemView(graph, s, vendor, category, item, w.itemApprovals)
            if (hidden.isNotEmpty()) {
                var showHidden by remember(category) { mutableStateOf(false) }
                TextButton(onClick = { showHidden = !showHidden }) {
                    Text("${if (showHidden) "Hide" else "Show"} ${hidden.size} comment(s) the decision model judged ungrounded")
                }
                if (showHidden) for (item in hidden) FeedbackItemView(graph, s, vendor, category, item, w.itemApprovals)
            }
            TextButton(onClick = { flow.addItem(vendor, category) }) { Text("+ Add a comment") }
            if (busy == null) {
                TextButton(onClick = { flow.checkDraft(vendor) }) { Text("Check again") }
            }
        }
    }

    val ready = w.allApproved()
    Text(
        "Review the draft and the comments, then approve it. Approving rewrites the draft with the comments you accepted and puts that letter on the Final tab. With nothing to fix, the Final tab shows this draft.",
        style = MaterialTheme.typography.bodySmall,
    )
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked = fancy, onCheckedChange = { fancy = it }, enabled = busy == null)
        Text("  Polish the wording after the rewrite", style = MaterialTheme.typography.bodyMedium)
    }
    Button(enabled = ready && busy == null, onClick = { flow.approveDraft(vendor, fancy) }, modifier = Modifier.fillMaxWidth()) {
        Text(if (ready) "Approve draft" else "Approve every comment first")
    }
}