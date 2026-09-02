package com.amr.data_collection_lab.collection

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.core.sync.FormManifestEntry
import com.dcp.core.sync.FormStore
import com.dcp.core.sync.SubmissionStore
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlinx.coroutines.runBlocking

/**
 * A submission opens against the version it was collected under (Form IR §9).
 *
 * This test exists because the break it watches was run and **nothing caught
 * it**: with `CollectionViewModel` choosing the newest version this device
 * holds instead of the submission's own, all 462 tests in this repository
 * passed — the 39 conformance vectors, both engines, `:shared:core`,
 * `:clients:composeApp` and the backend. On a device the same build rendered a
 * v1 draft under v2's labels, over v1's answers.
 *
 * Nothing below could see it. The vectors compare two engines and there is no
 * second implementation of a client. `:shared:core` knows about form versions
 * but not about which one a screen opens. The failure lives exactly in the gap
 * docs/project-conventions.md describes, and it is the quiet kind: the answers are still there,
 * the questions merely changed, and the enumerator has no way to notice that
 * the form in front of them is not the form they started.
 *
 * The fix was to remove the choice rather than only to test it — the ViewModel
 * is no longer handed a version it could get wrong, and asks
 * `FormCatalog.compiledFormForSubmission` instead. This test is what stops that
 * being undone.
 */
class FormVersionBindingTest {

    private class Fixture {
        val db: DcpDatabase = DcpDatabase(
            JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        )
        val submissions = SubmissionStore(db, deviceIdOverride = "dev-test")
        val forms = FormStore(db)
        val catalog = FormCatalog(forms, submissions)

        /** Delivers one version whose first question's label names the version. */
        fun deliver(version: Int, deployed: Boolean = true) {
            val held = forms.all().map {
                FormManifestEntry(it.formVersionId, it.formId, it.version, it.title, it.irChecksum)
            }
            val entry = FormManifestEntry(
                formVersionId = "fv-$version",
                formId = "household",
                version = version,
                title = "Household Survey",
                irChecksum = "sha256:v$version",
            )
            val manifest = if (deployed) held + entry else held
            forms.applyManifest(
                if (deployed) manifest else manifest + entry,
                mapOf(entry.formVersionId to ir(version)),
            )
        }

        private fun ir(version: Int) = """
            {"irVersion":"0.1","formId":"household","version":$version,
             "title":{"en":"Household Survey"},"defaultLanguage":"en","languages":["en"],
             "children":[{"type":"question","id":"enumerator_name","dataType":"text",
                          "label":{"en":"LABEL FROM V$version"}}]}
        """.trimIndent()
    }

    @Test
    fun `a draft opens against its own version, not the newest one delivered`() = runBlocking {
        val f = Fixture()
        f.deliver(1)
        val draft = f.submissions.createDraft("household", 1)

        // v2 deploys while that draft is still open on the device.
        f.deliver(2)

        val compiled = assertNotNull(f.catalog.compiledFormForSubmission(draft))
        assertEquals(1, compiled.version)
        assertEquals(
            "LABEL FROM V1",
            compiled.ir.children.first().label?.resolve("en"),
            "the draft was collected under v1 and must be shown v1's questions; " +
                "rendering v2 evaluates the enumerator's answers under rules " +
                "nobody asked them, and nothing on screen says so",
        )
    }

    @Test
    fun `a submission started after the new version opens against the new one`() = runBlocking {
        // The other direction, so the test above cannot pass by always
        // answering "v1" — which a hard-coded version would.
        val f = Fixture()
        f.deliver(1)
        f.deliver(2)
        val fresh = f.submissions.createDraft("household", 2)

        val compiled = assertNotNull(f.catalog.compiledFormForSubmission(fresh))
        assertEquals(2, compiled.version)
        assertEquals("LABEL FROM V2", compiled.ir.children.first().label?.resolve("en"))
    }

    @Test
    fun `a new submission is offered only the newest deployed version`() = runBlocking {
        val f = Fixture()
        f.deliver(1)
        f.deliver(2)

        assertEquals(listOf(2), f.catalog.startable().map { it.version })
    }

    @Test
    fun `a draft whose version this device no longer holds resolves to null`() = runBlocking {
        // Reachable only if retention failed. Null is what makes the screen say
        // which version is missing; a silently empty form would be read as data
        // loss, because that is exactly what it looks like.
        val f = Fixture()
        val orphan = f.submissions.createDraft("household", 9)

        assertNull(f.catalog.compiledFormForSubmission(orphan))
    }

    @Test
    fun `an unknown submission resolves to null rather than to some form`() = runBlocking {
        val f = Fixture()
        f.deliver(1)

        assertNull(f.catalog.compiledFormForSubmission("no-such-submission"))
    }
}
