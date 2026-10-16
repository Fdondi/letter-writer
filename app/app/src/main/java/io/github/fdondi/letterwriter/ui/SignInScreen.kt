package io.github.fdondi.letterwriter.ui

import android.app.Activity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.credentials.exceptions.GetCredentialCancellationException
import io.github.fdondi.letterwriter.auth.AuthManager
import kotlinx.coroutines.launch

@Composable
fun SignInScreen(auth: AuthManager, modifier: Modifier = Modifier) {
    val activity = LocalContext.current as Activity
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Letter Writer", style = MaterialTheme.typography.headlineMedium)
        Text(
            "Sign in with the Google account you use on the desktop app. " +
                "Your CV, examples, settings and API keys are read from that account.",
            textAlign = TextAlign.Center,
        )
        val problem = auth.configurationProblem
        if (problem != null) {
            Text(
                "Firebase is not configured for this build: $problem.",
                color = MaterialTheme.colorScheme.error,
                textAlign = TextAlign.Center,
            )
        }
        if (busy) {
            CircularProgressIndicator()
        } else {
            Button(
                enabled = problem == null,
                onClick = {
                    busy = true
                    error = null
                    scope.launch {
                        try {
                            auth.signIn(activity)
                        } catch (_: GetCredentialCancellationException) {
                            error = null
                        } catch (e: Exception) {
                            error = e.message ?: e.toString()
                        } finally {
                            busy = false
                        }
                    }
                },
            ) { Text("Sign in with Google") }
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center) }
    }
}
