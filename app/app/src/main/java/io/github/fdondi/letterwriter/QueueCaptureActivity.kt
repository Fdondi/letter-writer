package io.github.fdondi.letterwriter

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import io.github.fdondi.letterwriter.data.CaptureRequest
import io.github.fdondi.letterwriter.data.JobPageFetcher
import io.github.fdondi.letterwriter.pipeline.VendorFlowEngine
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * Queues a job posting the browser extension handed over (`letterwriter://capture?url=…&text=…`).
 * No UI: the app is signed in and writes Firestore like the share flow does, so the only thing to
 * show is the outcome. Firefox for Android has no extension sign-in API and no app server to POST
 * to, so the extension opens this URL instead (docs/JOB_CAPTURE_EXTENSION.md).
 */
class QueueCaptureActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val handoff = parseExtensionHandoff(intent?.data?.query)
        if (handoff == null) {
            toast("Letter Writer: that link carries no job page.")
            finish()
            return
        }
        val graph = (application as LetterWriterApp).graph
        val user = graph.auth.user.value
        if (user == null) {
            toast("Sign in to the Letter Writer app first, then send the page again.")
            finish()
            return
        }
        lifecycleScope.launch {
            val message = try {
                // No text in the URL (too big): download the page here, like the share flow does.
                val text = handoff.text ?: JobPageFetcher.fetch(handoff.url).text
                graph.opportunities.capture(user.sub, CaptureRequest(text = text, url = handoff.url, via = "extension")).message
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                "Could not queue the job: ${VendorFlowEngine.describe(e)}"
            }
            toast("Letter Writer: $message")
            finish()
        }
    }

    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
}
