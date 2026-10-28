package io.github.fdondi.letterwriter.ui.write

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.pipeline.ParagraphReview
import io.github.fdondi.letterwriter.pipeline.ReviewComment
import io.github.fdondi.letterwriter.pipeline.ReviewParagraph
import io.github.fdondi.letterwriter.pipeline.VendorWork
import io.github.fdondi.letterwriter.pipeline.WorkSession
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.SectionCard

/**
 * One vendor's letter, paragraph by paragraph, with the comments on each. Nothing blocks: a
 * paragraph is added as it is, or redrafted right away (through the API) with the comments ticked,
 * the answers given and an optional note.
 */
@Composable
fun VendorParagraphReview(graph: AppGraph, s: WorkSession, w: VendorWork, running: Map<String, String>) {
    val view = ParagraphReview.of(w)
    val commentCount = view.wholeLetter.size + view.paragraphs.sumOf { it.comments.size }
    SectionCard(vendorLabel(w.vendor)) {
        Text(
            listOf(
                "${view.paragraphs.size} paragraph(s)",
                if (commentCount > 0) "$commentCount comment(s)" else "no comments",
                if (w.paragraphEdits.isNotEmpty()) "${w.paragraphEdits.size} redrafted" else "",
            ).filter { it.isNotEmpty() }.joinToString(" · "),
            style = MaterialTheme.typography.bodySmall,
        )
        if (view.wholeLetter.isNotEmpty()) {
            Text("About the whole letter", style = MaterialTheme.typography.titleSmall)
            for (c in view.wholeLetter) key(c.id) { CommentRow(graph, s, w.vendor, c, picked = null, onPick = {}) }
        }
        for (p in view.paragraphs) key(p.index) { ParagraphCard(graph, s, w, p, running["paragraph:${w.vendor}:${p.index}"]) }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ParagraphCard(graph: AppGraph, s: WorkSession, w: VendorWork, p: ReviewParagraph, busy: String?) {
    val flow = graph.flow
    // Every comment is ticked: redrafting addresses them all unless some are unticked.
    var unpicked by remember(w.vendor, p.index, p.text) { mutableStateOf(setOf<String>()) }
    var note by remember(w.vendor, p.index, p.text) { mutableStateOf("") }
    val highlight = MaterialTheme.colorScheme.tertiaryContainer
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), border = CardDefaults.outlinedCardBorder()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            val ranges = p.comments.mapNotNull { it.highlight }.filter { it.first >= 0 && it.last < p.text.length }.sortedBy { it.first }
            Text(
                buildAnnotatedString {
                    var at = 0
                    for (r in ranges) {
                        if (r.first < at) continue
                        append(p.text.substring(at, r.first))
                        withStyle(SpanStyle(background = highlight)) { append(p.text.substring(r.first, r.last + 1)) }
                        at = r.last + 1
                    }
                    append(p.text.substring(at))
                },
                style = MaterialTheme.typography.bodyMedium,
            )
            if (p.redrafted) Text("Redrafted", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
            for (c in p.comments) key(c.id) {
                CommentRow(graph, s, w.vendor, c, picked = c.id !in unpicked) { on ->
                    unpicked = if (on) unpicked - c.id else unpicked + c.id
                }
            }
            OutlinedTextField(
                value = note,
                onValueChange = { note = it },
                label = { Text("Your note for a redraft (optional)") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 1,
            )
            if (busy != null) BusyRow(busy)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { flow.addParagraph(w.vendor, p.text) }) { Text("Add to your letter") }
                val picked = p.comments.filter { it.id !in unpicked }
                Button(enabled = busy == null, onClick = { flow.redraftParagraph(w.vendor, p.index, note, picked) }) {
                    Text(if (picked.isEmpty() && note.isBlank()) "Try another version" else "Redraft")
                }
                if (p.redrafted) TextButton(enabled = busy == null, onClick = { flow.restoreParagraph(w.vendor, p.index) }) { Text("Restore") }
            }
        }
    }
}

/** A comment; a question also takes the answer, saved on the item (and to the CV notes, as on the Letters tab). */
@Composable
private fun CommentRow(graph: AppGraph, s: WorkSession, vendor: String, c: ReviewComment, picked: Boolean?, onPick: (Boolean) -> Unit) {
    val item = c.item
    Row(verticalAlignment = Alignment.Top) {
        if (picked != null) Checkbox(checked = picked, onCheckedChange = onPick)
        Column(Modifier.weight(1f).padding(top = if (picked != null) 12.dp else 0.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(CATEGORY_LABELS[c.category] ?: c.category, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.SemiBold)
            Text(item["observation"].pyStr(), style = MaterialTheme.typography.bodySmall)
            if (c.highlight == null) {
                val quote = item["matched_text"].pyStr().ifBlank { item["quote"].pyStr() }
                if (quote.isNotBlank()) Text("“$quote”", style = MaterialTheme.typography.bodySmall, fontStyle = FontStyle.Italic)
            }
            if (c.isQuestion) QuestionAnswer(graph, s, vendor, c)
        }
    }
}

@Composable
private fun QuestionAnswer(graph: AppGraph, s: WorkSession, vendor: String, c: ReviewComment) {
    val item = c.item
    val saved = item["user_context"].pyStr()
    val suggestion = s.inputClusterText[item["input_cluster_key"].pyStr()].orEmpty()
    var answer by remember(c.id, saved) { mutableStateOf(saved.ifEmpty { suggestion }) }
    val question = item["user_instructions"].pyStr()
    if (question.isNotBlank()) Text(question, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
    OutlinedTextField(value = answer, onValueChange = { answer = it }, label = { Text("Your answer") }, modifier = Modifier.fillMaxWidth(), minLines = 1)
    if (answer.isNotBlank() && answer != saved) {
        TextButton(onClick = {
            graph.flow.answerInput(
                vendor,
                c.category,
                c.id,
                answer,
                toCv = item["persist_user_context_to_cv"].asBooleanOrNull() != false,
                toAgents = item["persist_user_context_for_agents"].asBooleanOrNull() != false,
            )
        }) { Text(if (saved.isEmpty()) "Save answer" else "Update answer") }
    } else if (saved.isNotEmpty()) {
        Text("Answer saved; a redraft uses it.", style = MaterialTheme.typography.bodySmall)
    }
}
