package io.github.fdondi.letterwriter

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import io.github.fdondi.letterwriter.ui.SignInScreen
import io.github.fdondi.letterwriter.ui.SignedInRoot
import io.github.fdondi.letterwriter.ui.theme.LetterWriterTheme

class MainActivity : ComponentActivity() {
    private val graph get() = (application as LetterWriterApp).graph

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleShare(intent)
        setContent {
            LetterWriterTheme {
                val user by graph.auth.user.collectAsState()
                val signedIn = user
                if (signedIn != null) {
                    SignedInRoot(graph, signedIn)
                } else {
                    Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                        SignInScreen(graph.auth, Modifier.padding(padding))
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    private fun handleShare(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND || intent.type != "text/plain") return
        intent.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.isNotBlank() }?.let { graph.incomingShare.value = it }
    }
}
