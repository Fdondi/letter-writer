package io.github.fdondi.letterwriter.pipeline

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test
import java.nio.file.Files

class WorkSessionStoreTest {
    /** Graphs are rebuilt when demo mode is entered or left; they must share the one DataStore per file. */
    @Test
    fun oneStorePerFileAndItKeepsWorkingAcrossGraphs() = runTest {
        val dir = Files.createTempDirectory("lw-work").toFile()
        val file = dir.resolve("datastore/work_session.json")
        val first = WorkSessionStore.at(file)
        assertSame(first, WorkSessionStore.at(dir.resolve("datastore/../datastore/work_session.json")))

        first.update { WorkSession(intake = JobIntake(jobText = "Posting")) }
        assertEquals("Posting", WorkSessionStore.at(file).current()?.intake?.jobText)

        WorkSessionStore.at(file).update { null }
        assertNull(first.current())
        dir.deleteRecursively()
    }
}
