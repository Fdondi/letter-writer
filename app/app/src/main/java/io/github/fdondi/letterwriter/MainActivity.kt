package io.github.fdondi.letterwriter

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.fdondi.letterwriter.demo.DemoMode
import io.github.fdondi.letterwriter.ui.CrashReportCard
import io.github.fdondi.letterwriter.ui.SignInScreen
import io.github.fdondi.letterwriter.ui.SignedInRoot
import io.github.fdondi.letterwriter.ui.theme.LetterWriterTheme

class MainActivity : ComponentActivity() {
    private val app get() = application as LetterWriterApp
    private val graph get() = app.graph

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleDemoFlag(intent)
        handleShare(intent)
        setContent {
            LetterWriterTheme {
                val current by app.graphs.collectAsState()
                val graph = current ?: return@LetterWriterTheme
                // A new graph (demo entered or left) starts every screen afresh.
                key(graph) {
                    val user by graph.auth.user.collectAsState()
                    val signedIn = user
                    if (signedIn != null) {
                        SignedInRoot(graph, signedIn)
                    } else {
                        Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                            Column(Modifier.padding(padding)) {
                                CrashReportCard(Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                                SignInScreen(graph.auth, onDemo = { app.setDemoMode(true) })
                            }
                        }
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleDemoFlag(intent)
        handleShare(intent)
    }

    /** `--ez io.github.fdondi.letterwriter.DEMO true|false` from adb (scripted tests). */
    private fun handleDemoFlag(intent: Intent?) {
        if (intent?.hasExtra(DemoMode.EXTRA) == true) app.setDemoMode(intent.getBooleanExtra(DemoMode.EXTRA, false))
    }

    private fun handleShare(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND || intent.type != "text/plain") return
        intent.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.isNotBlank() }?.let { graph.incomingShare.value = it }
    }
}
