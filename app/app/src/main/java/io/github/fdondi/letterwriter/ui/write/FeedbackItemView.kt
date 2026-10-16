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
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.core.asBooleanOrNull
import io.github.fdondi.letterwriter.core.asDoubleOrNull
import io.github.fdondi.letterwriter.core.asObjectOrNull
import io.github.fdondi.letterwriter.core.pyStr
import io.github.fdondi.letterwriter.decision.DecisionKeys
import io.github.fdondi.letterwriter.pipeline.FeedbackItems
import io.github.fdondi.letterwriter.pipeline.FeedbackUi
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.pipeline.WorkSession
import io.github.fdondi.letterwriter.ui.common.PersistedTextField
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.util.Locale

private val SOURCE_LABELS = mapOf(
    "CV" to "CV",
    "EXAMPLE" to "Example letter",
    "BACKGROUND_RESEARCH" to "Company research",
    "LETTER" to "Letter",
    "USER" to "You",
)

/** One comment with its actions: approve, edit, answer a question, add or find context, remove. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FeedbackItemView(graph: AppGraph, s: WorkSession, vendor: String, category: String, item: JsonObject, approvals: Map<String, Boolean>) {
    val flow = graph.flow
    val id = item["id"].pyStr()
    val isFix = item["type"].pyStr() == FeedbackUi.PLEASE_FIX
    val status = item["status"].pyStr().uppercase()
    val approved = FeedbackUi.itemIsApproved(item, approvals)
    val hidden = FeedbackUi.isHidden(item)
    val scope = rememberCoroutineScope()
    var requesting by remember(id) { mutableStateOf(false) }
    var requestResult by remember(id) { mutableStateOf<String?>(null) }

    val container = when {
        !isFix -> MaterialTheme.colorScheme.surfaceVariant
        approved -> MaterialTheme.colorScheme.secondaryContainer
        else -> MaterialTheme.colorScheme.surface
    }
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = container), border = CardDefaults.outlinedCardBorder()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (isFix) "To fix" else "Already good",
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = if (isFix) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                decisionLabel(item)?.let { Text(it, style = MaterialTheme.typography.labelSmall) }
            }
            if (isFix) {
                PersistedTextField(item["observation"].pyStr(), { flow.editObservation(vendor, category, id, it) }, "Comment", key = "${s.sessionId}/$vendor/$id/obs", minLines = 1)
            } else {
                Text(item["observation"].pyStr(), style = MaterialTheme.typography.bodyMedium)
            }
            val quote = item["matched_text"].pyStr().ifBlank { item["quote"].pyStr() }
            if (quote.isNotBlank()) Text("“$quote”", style = MaterialTheme.typography.bodySmall, fontStyle = FontStyle.Italic)

            if (isFix && status == "INPUT_NEEDED") {
                InputNeeded(graph, s, vendor, category, item)
            } else if (isFix) {
                val rows = FeedbackItems.contextItems(item).mapNotNull { it.asObjectOrNull() }
                rows.forEachIndexed { idx, row ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("${SOURCE_LABELS[row["source"].pyStr()] ?: row["source"].pyStr()}: ${row["text"].pyStr()}", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                        TextButton(onClick = { flow.setContextRows(vendor, category, id, rows.filterIndexed { i, _ -> i != idx }) }) { Text("Remove") }
                    }
                }
                if (requesting) {
                    Text("Looking for more context…", style = MaterialTheme.typography.bodySmall)
                } else {
                    TextButton(onClick = {
                        requesting = true
                        requestResult = null
                        scope.launch {
                            requestResult = try {
                                val n = flow.requestContext(vendor, category, id)
                                if (n == 0) "No additional context lines found in the same materials." else "Added $n context line(s)."
                            } catch (e: Exception) {
                                "Could not get more context: ${VendorFlowEngine.describe(e)}"
                            }
                            requesting = false
                        }
                    }) { Text("Find supporting context") }
                }
                requestResult?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
            }

            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (isFix && status != "INPUT_NEEDED") {
                    if (approved) {
                        OutlinedButton(onClick = { flow.unapproveItem(vendor, category, id) }) { Text("Approved ✓") }
                    } else {
                        Button(onClick = { flow.approveItem(vendor, category, id) }) { Text(if (hidden) "Keep and approve" else "Approve") }
                    }
                }
                TextButton(onClick = { flow.removeItem(vendor, category, id) }) { Text("Remove") }
            }
        }
    }
}

private fun decisionLabel(item: JsonObject): String? {
    val verdict = item[DecisionKeys.VERDICT].pyStr().lowercase()
    val p = item[DecisionKeys.VALID_PROBABILITY].asDoubleOrNull()
    val pct = p?.let { String.format(Locale.US, " %.0f%%", it * 100) }.orEmpty()
    val restored = item[DecisionKeys.RESTORED].asBooleanOrNull() == true
    return when (verdict) {
        DecisionKeys.VERDICT_VALID -> "Grounded$pct"
        DecisionKeys.VERDICT_INVALID -> if (restored) "Kept by you (judged ungrounded$pct)" else "Judged ungrounded$pct"
        DecisionKeys.VERDICT_UNCALIBRATED -> "Grounded$pct (no hide threshold)"
        DecisionKeys.VERDICT_UNSCORED -> "Not scored"
        else -> null
    }
}

/** An INPUT_NEEDED comment: the model's question, the user's answer and where it is remembered. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun InputNeeded(graph: AppGraph, s: WorkSession, vendor: String, category: String, item: JsonObject) {
    val flow = graph.flow
    val id = item["id"].pyStr()
    val saved = item["user_context"].pyStr()
    val cluster = item["input_cluster_key"].pyStr()
    val suggestion = s.inputClusterText[cluster].orEmpty()
    var answer by remember(id, saved) { mutableStateOf(saved.ifEmpty { suggestion }) }
    var toCv by remember(id) { mutableStateOf(item["persist_user_context_to_cv"].asBooleanOrNull() != false) }
    var toAgents by remember(id) { mutableStateOf(item["persist_user_context_for_agents"].asBooleanOrNull() != false) }
    val declined = item["input_declined"].asBooleanOrNull() == true

    val question = item["user_instructions"].pyStr()
    Text(if (question.isNotBlank()) question else "The model needs information from you to fix this.", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
    if (saved.isEmpty() && suggestion.isNotEmpty()) Text("Pre-filled from your answer to the same question in another vendor.", style = MaterialTheme.typography.bodySmall)
    OutlinedTextField(value = answer, onValueChange = { answer = it }, label = { Text("Your answer") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        FilterChip(selected = toCv, onClick = { toCv = !toCv }, label = { Text("Add to CV notes") })
        FilterChip(selected = toAgents, onClick = { toAgents = !toAgents }, label = { Text("Remember for future letters") })
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(enabled = answer.isNotBlank(), onClick = {
            flow.answerInput(vendor, category, id, answer, toCv, toAgents)
        }) { Text(if (saved.isNotEmpty()) "Update answer" else "Save answer") }
        if (!declined && saved.isEmpty()) OutlinedButton(onClick = { flow.declineInput(vendor, category, id) }) { Text("Skip, no answer") }
    }
    if (declined) Text("Skipped: the rewrite proceeds without this information.", style = MaterialTheme.typography.bodySmall)
}
