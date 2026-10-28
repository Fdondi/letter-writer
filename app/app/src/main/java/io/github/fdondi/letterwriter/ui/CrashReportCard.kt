package io.github.fdondi.letterwriter.ui

import android.content.ClipData
import android.content.Intent
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.core.CrashLog
import kotlinx.coroutines.launch

/** The last crash, shown once on the next start with its stack trace to copy or share. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CrashReportCard(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    var report by remember { mutableStateOf(runCatching { CrashLog.lastReport(context) }.getOrNull()) }
    var expanded by remember { mutableStateOf(false) }
    val r = report ?: return
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(r.summary, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onErrorContainer)
            if (expanded) {
                Text(
                    r.details,
                    modifier = Modifier.heightIn(max = 280.dp).verticalScroll(rememberScrollState()).horizontalScroll(rememberScrollState()),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    softWrap = false,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Hide details" else "Details") }
                TextButton(onClick = {
                    scope.launch { runCatching { clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Crash report", r.details))) } }
                }) { Text("Copy") }
                TextButton(onClick = {
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = "text/plain"
                        putExtra(Intent.EXTRA_SUBJECT, "Letter Writer crash report")
                        putExtra(Intent.EXTRA_TEXT, r.details)
                    }
                    runCatching { context.startActivity(Intent.createChooser(send, "Share the crash report")) }
                }) { Text("Share") }
                TextButton(onClick = {
                    CrashLog.dismiss(context)
                    report = null
                }) { Text("Dismiss") }
            }
        }
    }
}
