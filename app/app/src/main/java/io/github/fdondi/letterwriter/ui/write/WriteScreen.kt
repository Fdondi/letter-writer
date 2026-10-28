package io.github.fdondi.letterwriter.ui.write

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.ui.intake.IntakeScreen

/** Tabs of [WriteScreen], as ints so the shell can keep the selection across rotations. */
object WriteTab {
    const val JOB = 0
    const val LETTERS = 1
    const val FINAL = 2
}

/** The letter in progress: job intake, the vendor columns, and the assembled final letter. */
@Composable
fun WriteScreen(
    graph: AppGraph,
    tab: Int,
    onTab: (Int) -> Unit,
    onSentToPipeline: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val session by graph.flow.session.collectAsState()
    val hasSession = session != null
    val shown = if (hasSession) tab else WriteTab.JOB
    Column(modifier) {
        PrimaryTabRow(selectedTabIndex = shown) {
            Tab(selected = shown == WriteTab.JOB, onClick = { onTab(WriteTab.JOB) }, text = { Text("Job") })
            Tab(selected = shown == WriteTab.LETTERS, enabled = hasSession, onClick = { onTab(WriteTab.LETTERS) }, text = { Text("Letters") })
            Tab(selected = shown == WriteTab.FINAL, enabled = hasSession, onClick = { onTab(WriteTab.FINAL) }, text = { Text("Final") })
        }
        val content = Modifier.fillMaxSize()
        when (shown) {
            WriteTab.JOB -> IntakeScreen(graph, onStartWriting = { onTab(WriteTab.LETTERS) }, onSentToPipeline = onSentToPipeline, modifier = content)
            WriteTab.LETTERS -> VendorFlowScreen(graph, onGoToFinal = { onTab(WriteTab.FINAL) }, modifier = content)
            else -> AssemblyScreen(graph, content)
        }
    }
}
