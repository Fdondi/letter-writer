package io.github.fdondi.letterwriter.ui.write

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.ui.intake.IntakeScreen

/** The letter in progress: job intake, the vendor columns, and the assembled final letter. */
@Composable
fun WriteScreen(graph: AppGraph, modifier: Modifier = Modifier) {
    val session by graph.flow.session.collectAsState()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val hasSession = session != null
    if (!hasSession) tab = 0
    Column(modifier) {
        PrimaryTabRow(selectedTabIndex = tab) {
            Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Job") })
            Tab(selected = tab == 1, enabled = hasSession, onClick = { tab = 1 }, text = { Text("Letters") })
            Tab(selected = tab == 2, enabled = hasSession, onClick = { tab = 2 }, text = { Text("Final") })
        }
        val content = Modifier.fillMaxSize()
        when (tab) {
            0 -> IntakeScreen(graph, onStartWriting = { tab = 1 }, modifier = content)
            1 -> VendorFlowScreen(graph, onGoToFinal = { tab = 2 }, modifier = content)
            else -> AssemblyScreen(graph, content)
        }
    }
}
