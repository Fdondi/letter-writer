package io.github.fdondi.letterwriter.ui.settings

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.auth.BigQueryAuth
import io.github.fdondi.letterwriter.cost.BigQueryConsentRequired
import io.github.fdondi.letterwriter.cost.CostLine
import io.github.fdondi.letterwriter.cost.CostSyncState
import io.github.fdondi.letterwriter.cost.MonthlyCost
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.common.SectionCard
import io.github.fdondi.letterwriter.ui.common.WarningList
import io.github.fdondi.letterwriter.ui.common.formatDollars
import io.github.fdondi.letterwriter.ui.write.vendorLabel
import kotlinx.coroutines.launch

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CostsScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    val sync by graph.costs.state.collectAsState()
    val pending by graph.costs.pendingRows.collectAsState()
    val unpriced by graph.costs.unpricedModels.collectAsState()
    var pendingCost by remember { mutableDoubleStateOf(0.0) }
    var monthsBack by remember { mutableIntStateOf(1) }
    var reload by remember { mutableIntStateOf(0) }
    var summary by remember { mutableStateOf<MonthlyCost?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var consent by remember { mutableStateOf<BigQueryAuth.NeedsConsent?>(null) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) {
        consent = null
        reload++
    }

    LaunchedEffect(pending) { pendingCost = runCatching { graph.costs.pendingCost() }.getOrDefault(0.0) }
    LaunchedEffect(monthsBack, reload) {
        loading = true
        error = null
        consent = null
        try {
            summary = graph.costs.monthlySummary(graph.auth.requireUser().sub, monthsBack)
        } catch (e: BigQueryConsentRequired) {
            consent = e.consent
            error = e.message
        } catch (e: Exception) {
            summary = null
            error = "Could not read costs from BigQuery: ${VendorFlowEngine.describe(e)}"
        } finally {
            loading = false
        }
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SectionCard("Upload") {
            val line = when (val st = sync) {
                CostSyncState.Idle -> "Not uploaded yet in this session."
                CostSyncState.Syncing -> "Uploading…"
                is CostSyncState.Synced -> "Uploaded."
                is CostSyncState.Failed -> "Upload failed: ${st.message}"
            }
            Text(line, style = MaterialTheme.typography.bodySmall)
            Text("$pending cost record(s) waiting on the phone (${formatDollars(pendingCost)}). They are kept until BigQuery accepts them.", style = MaterialTheme.typography.bodySmall)
            if (pending > 0) OutlinedButton(onClick = { scope.launch { graph.costs.flush(); reload++ } }) { Text("Upload now") }
            if (unpriced.isNotEmpty()) WarningList(listOf("No price known for: ${unpriced.joinToString(", ")}. Their cost is recorded as 0."))
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for ((m, label) in listOf(1 to "This month", 3 to "3 months", 12 to "12 months")) {
                FilterChip(selected = monthsBack == m, onClick = { monthsBack = m }, label = { Text(label) })
            }
        }
        if (loading) BusyRow("Reading BigQuery")
        ErrorText(error)
        consent?.let { c -> Button(onClick = { launcher.launch(IntentSenderRequest.Builder(c.intent).build()) }) { Text("Allow BigQuery access") } }

        summary?.let { s ->
            SectionCard("Total") {
                Text(formatDollars(s.totalCost), style = MaterialTheme.typography.headlineSmall)
                Text("${s.totalRequests} requests · ${s.letterCount} letters", style = MaterialTheme.typography.bodySmall)
            }
            SectionCard("By vendor") {
                for ((v, l) in s.byVendor.entries.sortedByDescending { it.value.totalCost }) CostRow(vendorLabel(v), l)
            }
            SectionCard("By step") {
                for ((p, l) in s.byPhase.entries.sortedByDescending { it.value.totalCost }) CostRow(p, l)
            }
        }
    }
}

@Composable
private fun CostRow(label: String, line: CostLine) {
    Row {
        Column(Modifier.weight(1f)) {
            Text(label, fontWeight = FontWeight.Medium)
            Text(
                "${line.requestCount} requests · ${line.inputTokens} in / ${line.outputTokens} out tokens" +
                    (line.costPerLetter?.let { " · ${formatDollars(it)} per letter" } ?: ""),
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Text(formatDollars(line.totalCost))
    }
}
