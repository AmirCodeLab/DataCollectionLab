package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The failure item 4 exists to prevent, walked end to end (analysis §2, first
 * failure).
 *
 * Forms are updated at the office in the morning: v3, which was published
 * against `villages` v8. Reference data was last fetched a month ago: v7. The
 * device holds v7's rows and not v8's. The enumerator walks to the village,
 * opens an interview, and the roster is empty.
 *
 * **The dataset store is already right about the rows** and has been since
 * phase 2: it will not serve v7's rows for a form version pinned to v8, because
 * a wrong list is worse than no list (break 30). What it cannot do is stop the
 * interview being *filed*. If the roster is a `rowSource` repeat, or the select
 * is optional, the submission finalises and records a household with no
 * members — every screen correct, the data wrong, and nothing anywhere in an
 * error state.
 *
 * This test was written before the feature and watched to fail against the
 * behaviour on main, which is that nothing blocks finalisation.
 */
class ReferenceDataReadinessTest {

    private class Fixture {
        val db: DcpDatabase = DcpDatabase(
            JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        )
        val forms = FormStore(db)
        val datasets = DatasetStore(db)
        val submissions = SubmissionStore(db, deviceIdOverride = "dev-test")
        val referenceData = ReferenceData(forms, datasets, submissions)

        /** A form version, held and deployed, as a form sync leaves it. */
        fun deliverForm(formVersionId: String, version: Int) {
            val held = forms.all().map {
                FormManifestEntry(it.formVersionId, it.formId, it.version, it.title, it.irChecksum)
            }
            val entry = FormManifestEntry(
                formVersionId = formVersionId,
                formId = "household_survey",
                version = version,
                title = "Household Survey",
                irChecksum = "sha256:v$version",
            )
            forms.applyManifest(held + entry, mapOf(formVersionId to """{"formId":"household_survey"}"""))
        }

        fun pin(formVersionId: String, datasetVersionId: String, version: Int, rowCount: Int) =
            DatasetManifestEntry(
                formVersionId = formVersionId,
                datasetKey = "villages",
                datasetVersionId = datasetVersionId,
                version = version,
                rowCount = rowCount,
                checksum = "sha256:$datasetVersionId",
                filterColumns = listOf("name"),
            )

        fun rows(vararg keys: String) =
            keys.map { it to """{"name":"$it","label":"Village $it"}""" }
    }

    /** Last month's sync: fv-2 pinned villages v7, and every page arrived. */
    private fun Fixture.lastMonth() {
        deliverForm("fv-2", 2)
        val v7 = pin("fv-2", "dv-7", 7, rowCount = 2)
        datasets.applyManifest(listOf(v7))
        datasets.appendRows("dv-7", rows("V1", "V2"), nextCursor = null)
    }

    /**
     * This morning's form sync: fv-3, which pins villages v8. The dataset
     * manifest rode along, so the pin is known; no row of v8 has arrived.
     */
    private fun Fixture.thisMorning(rowCount: Int = 38_000) {
        deliverForm("fv-3", 3)
        datasets.applyManifest(
            listOf(pin("fv-2", "dv-7", 7, rowCount = 2), pin("fv-3", "dv-8", 8, rowCount)),
        )
    }

    @Test
    fun `the roster is empty, and the store is right to make it empty`() {
        val f = Fixture()
        f.lastMonth()
        f.thisMorning()

        // v7 is whole and still resolves for the form version that pinned it.
        assertEquals(listOf("V1", "V2"), f.datasets.rowsFor("fv-2", "villages").map { it.first })
        // v8 is pinned by this morning's form and no row of it is here. An
        // empty list, never last month's list under a new form's questions.
        assertTrue(f.datasets.rowsFor("fv-3", "villages").isEmpty())
    }

    @Test
    fun `a submission on that form cannot be finalised, and the refusal names the list and the action`() {
        val f = Fixture()
        f.lastMonth()
        f.thisMorning()
        val draft = f.submissions.createDraft("household_survey", 3)

        val readiness = f.referenceData.readinessOfSubmission(draft)

        assertFalse(readiness.isReady, "a submission whose pinned list is absent must not finalise")
        assertEquals(listOf("villages v8 — not downloaded"), readiness.statusLines())
        val refusal = assertNotNull(readiness.refusal())
        assertTrue("villages v8" in refusal, refusal)
        assertTrue("Reference data" in refusal, refusal)
        assertEquals(
            "Cannot finalise: villages v8 not downloaded — tap Reference data.",
            refusal,
        )
    }

    @Test
    fun `a transfer that stopped part way is not ready, and says how far it got`() {
        val f = Fixture()
        f.thisMorning(rowCount = 38_000)
        f.datasets.appendRows("dv-8", f.rows("V1", "V2", "V3"), nextCursor = "cursor-3")
        val draft = f.submissions.createDraft("household_survey", 3)

        val readiness = f.referenceData.readinessOfSubmission(draft)

        assertFalse(readiness.isReady, "a partial list is not the list")
        assertEquals(listOf("villages v8 — 3 of 38,000 rows"), readiness.statusLines())
        assertEquals(
            "Cannot finalise: villages v8 has 3 of 38,000 rows — tap Reference data.",
            readiness.refusal(),
        )
    }

    @Test
    fun `a form version whose pinned lists are all whole is ready and says nothing`() {
        val f = Fixture()
        f.lastMonth()
        val draft = f.submissions.createDraft("household_survey", 2)

        val readiness = f.referenceData.readinessOfSubmission(draft)

        assertTrue(readiness.isReady)
        assertEquals(emptyList(), readiness.statusLines())
        assertNull(readiness.refusal())
    }

    @Test
    fun `a form version pinning nothing is ready — no reference data is not missing reference data`() {
        val f = Fixture()
        f.deliverForm("fv-1", 1)
        val draft = f.submissions.createDraft("household_survey", 1)

        assertTrue(f.referenceData.readinessOfSubmission(draft).isReady)
    }

    @Test
    fun `a submission on a version this device does not hold is not blocked by this rule`() {
        // Retention failed, or a draft outlived its version. That is the
        // missing-form-version state the collection screen already names; it
        // is not a reference-data refusal, and answering "not ready" here
        // would put the wrong sentence in front of the enumerator.
        val f = Fixture()
        val draft = f.submissions.createDraft("household_survey", 9)

        assertTrue(f.referenceData.readinessOfSubmission(draft).isReady)
    }
}
