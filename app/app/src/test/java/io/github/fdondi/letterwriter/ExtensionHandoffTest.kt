package io.github.fdondi.letterwriter

import java.net.URLEncoder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ExtensionHandoffTest {
    @Test
    fun fullHandoffCarriesUrlAndText() {
        val handoff = parseExtensionHandoff("url=${enc(JOB)}&text=${enc("Posting text")}")
        assertEquals(JOB, handoff?.url)
        assertEquals("Posting text", handoff?.text)
    }

    @Test
    fun missingTextMeansTheAppFetchesThePage() {
        val handoff = parseExtensionHandoff("url=${enc(JOB)}")
        assertEquals(JOB, handoff?.url)
        assertNull(handoff?.text)
    }

    @Test
    fun blankTextMeansTheAppFetchesThePage() {
        assertNull(parseExtensionHandoff("url=${enc(JOB)}&text=")?.text)
    }

    @Test
    fun noHttpUrlMeansNoHandoff() {
        assertNull(parseExtensionHandoff(null))
        assertNull(parseExtensionHandoff(""))
        assertNull(parseExtensionHandoff("text=only"))
        assertNull(parseExtensionHandoff("url=ftp://example.com/x"))
        assertNull(parseExtensionHandoff("url=letterwriter://capture"))
    }

    @Test
    fun formEncodingRoundTrips() {
        // The same encoding URLSearchParams produces in the extension.
        val tricky = "Stelle & Titel — 100% «remote» in Zürich\nzweite Zeile + mehr"
        val handoff = parseExtensionHandoff("url=${enc(JOB)}&text=${enc(tricky)}")
        assertEquals(tricky, handoff?.text)
        assertEquals(JOB, handoff?.url)
    }

    private fun enc(value: String) = URLEncoder.encode(value, "UTF-8")

    companion object {
        const val JOB = "https://www.jobs.ch/de/stellenangebote/detail/11111111-2222-4333-8444-555555555555/"
    }
}
