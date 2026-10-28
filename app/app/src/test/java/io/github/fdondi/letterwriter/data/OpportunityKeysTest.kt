package io.github.fdondi.letterwriter.data

import io.github.fdondi.letterwriter.core.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Same cases as `letter_writer/test_opportunity_store.py`: the desktop and the phone must agree on keys and ids. */
class OpportunityKeysTest {
    private val repoRoot = File(System.getProperty("letterwriter.repoRoot") ?: error("letterwriter.repoRoot system property not set"))
    private val fixture = Json.parse(repoRoot.resolve("letter_writer/tests/fixtures/opportunity_keys.json").readText()).jsonObject

    private fun JsonObject.s(key: String) = getValue(key).jsonPrimitive.content

    @Test
    fun canonicalKeysCleanUrlsAndSourcesMatchTheDesktop() {
        val cases = fixture.getValue("canonical_keys").jsonArray.map { it.jsonObject }
        assertTrue(cases.size >= 10)
        for (c in cases) {
            val url = c.s("url")
            assertEquals("canonical_key of $url", c.s("canonical_key"), OpportunityKeys.canonicalKey(url))
            assertEquals("clean_url of $url", c.s("clean_url"), OpportunityKeys.cleanUrl(url))
            assertEquals("source of $url", c.s("source"), OpportunityKeys.sourceOf(c.s("canonical_key")))
        }
    }

    @Test
    fun textKeysMatchTheDesktop() {
        for (c in fixture.getValue("text_keys").jsonArray.map { it.jsonObject }) {
            assertEquals("text_key of ${c.s("text")}", c.s("text_key"), OpportunityKeys.textKey(c.s("text")))
        }
    }

    @Test
    fun documentIdsMatchTheDesktop() {
        val user = fixture.s("user_id")
        for (c in fixture.getValue("document_ids").jsonArray.map { it.jsonObject }) {
            assertEquals(c.s("document_id"), OpportunityKeys.documentId(user, c.s("canonical_key")))
        }
    }
}
