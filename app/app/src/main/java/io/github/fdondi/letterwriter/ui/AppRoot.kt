package io.github.fdondi.letterwriter.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.Button
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.AppGraph
import io.github.fdondi.letterwriter.auth.SignedInUser
import io.github.fdondi.letterwriter.cost.CostSyncState
import io.github.fdondi.letterwriter.data.ProfileMissingException
import io.github.fdondi.letterwriter.ui.common.BusyRow
import io.github.fdondi.letterwriter.ui.common.ErrorText
import io.github.fdondi.letterwriter.ui.settings.CostsScreen
import io.github.fdondi.letterwriter.ui.settings.CvScreen
import io.github.fdondi.letterwriter.ui.settings.ExamplesScreen
import io.github.fdondi.letterwriter.ui.settings.InstructionsScreen
import io.github.fdondi.letterwriter.ui.settings.SettingsScreen
import io.github.fdondi.letterwriter.ui.write.WriteScreen
import kotlinx.coroutines.launch

private enum class Destination(val title: String) {
    WRITE("Write a letter"),
    CV("CV"),
    EXAMPLES("Previous examples"),
    INSTRUCTIONS("AI instructions"),
    SETTINGS("Settings"),
    COSTS("Costs"),
}

private sealed interface Boot {
    data object Loading : Boot
    data object Ready : Boot
    data class Failed(val message: String) : Boot
}

/** Loads the profile and API keys for [user], then shows the app. */
@Composable
fun SignedInRoot(graph: AppGraph, user: SignedInUser) {
    var attempt by remember { mutableIntStateOf(0) }
    var boot by remember(user.sub) { mutableStateOf<Boot>(Boot.Loading) }
    LaunchedEffect(user.sub, attempt) {
        boot = Boot.Loading
        boot = try {
            graph.profiles.load(user.sub)
            graph.apiKeys.value = graph.profiles.loadApiKeys(user.sub)
            graph.costs.init()
            Boot.Ready
        } catch (e: ProfileMissingException) {
            Boot.Failed(e.message ?: "No profile for this account")
        } catch (e: Exception) {
            Boot.Failed("Could not load your profile: ${e.message ?: e::class.simpleName}")
        }
        if (boot == Boot.Ready) graph.costs.flush()
    }
    when (val b = boot) {
        Boot.Loading -> Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center) { BusyRow("Loading your profile") }
        is Boot.Failed -> Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically)) {
            ErrorText(b.message)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { attempt++ }) { Text("Retry") }
                TextButton(onClick = { graph.auth.signOut() }) { Text("Sign out") }
            }
        }
        Boot.Ready -> AppShell(graph, user)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AppShell(graph: AppGraph, user: SignedInUser) {
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    var destination by rememberSaveable { mutableStateOf(Destination.WRITE) }
    val snackbar = remember { SnackbarHostState() }
    val message by graph.flow.message.collectAsState()
    val shared by graph.incomingShare.collectAsState()

    LaunchedEffect(message) {
        val m = message ?: return@LaunchedEffect
        snackbar.showSnackbar(m)
        graph.flow.dismissMessage()
    }
    LaunchedEffect(shared) {
        if (shared != null) destination = Destination.WRITE
    }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet {
                Text(user.email ?: user.displayName.orEmpty(), Modifier.padding(16.dp), style = MaterialTheme.typography.titleSmall)
                for (d in Destination.entries) {
                    NavigationDrawerItem(
                        label = { Text(d.title) },
                        selected = d == destination,
                        onClick = {
                            destination = d
                            scope.launch { drawer.close() }
                        },
                        modifier = Modifier.padding(horizontal = 12.dp),
                    )
                }
                TextButton(onClick = { graph.auth.signOut() }, modifier = Modifier.padding(16.dp)) { Text("Sign out") }
            }
        },
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text(destination.title) },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawer.open() } }) { Icon(Icons.Filled.Menu, contentDescription = "Menu") }
                    },
                )
            },
            snackbarHost = { SnackbarHost(snackbar) },
        ) { padding ->
            Column(Modifier.padding(padding).fillMaxSize()) {
                CostConsentBanner(graph)
                val content = Modifier.fillMaxSize()
                when (destination) {
                    Destination.WRITE -> WriteScreen(graph, content)
                    Destination.CV -> CvScreen(graph, content)
                    Destination.EXAMPLES -> ExamplesScreen(graph, content)
                    Destination.INSTRUCTIONS -> InstructionsScreen(graph, content)
                    Destination.SETTINGS -> SettingsScreen(graph, content)
                    Destination.COSTS -> CostsScreen(graph, content)
                }
            }
        }
    }
}

/** BigQuery needs a one-time OAuth consent before queued costs can be uploaded. */
@Composable
private fun CostConsentBanner(graph: AppGraph) {
    val state by graph.costs.state.collectAsState()
    val scope = rememberCoroutineScope()
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) {
        scope.launch { graph.costs.flush() }
    }
    val failed = state as? CostSyncState.Failed ?: return
    val consent = failed.needsConsent ?: return
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(failed.message, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
        TextButton(onClick = { launcher.launch(IntentSenderRequest.Builder(consent.intent).build()) }) { Text("Allow") }
    }
}
