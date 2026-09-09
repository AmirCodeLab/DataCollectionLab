package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.core.db.SyncQueries
import com.dcp.form.FormValue
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The assignment statement on the device, and the one thing it must never do.
 *
 * Item 2's analysis (§4.3) names the worst outcome: an enumerator's draft
 * lost silently because the case under it moved. A release arrives as an
 * absence from a complete statement, so the device has to notice it, say it,
 * and keep everything — the case row, so the list can name what the draft
 * was for, and the draft, finishable and pushable.
 */
class CaseStoreTest {

    private fun db(): DcpDatabase =
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))

    private fun case(id: String, key: String, head: String = "Amina") = AssignedCase(
        caseId = id,
        caseKey = key,
        datasetKey = "village",
        status = "open",
        priority = 0,
        dueAt = null,
        dataJson = """{"case_key":"$key","headName":"$head","hhSize":4}""",
    )

    @Test
    fun `a statement is complete, so absence is a release and the row is kept`() {
        val database = db()
        val cases = CaseStore(database)
        val store = SubmissionStore(database)

        cases.applyStatement(listOf(case("c1", "S3|1|1"), case("c2", "S3|1|2")))
        assertEquals(listOf("S3|1|1", "S3|1|2"), cases.list().map { it.caseKey })
        assertTrue(cases.list().all { it.assigned })

        // Work opened against c1, with a draft on it.
        val draft = store.createDraft("hh", 1, caseId = "c1")
        store.appendOp(draft, "hh", 1, OpKind.SET, "q", FormValue.Text("first"))

        // The supervisor moves c1 away: the next statement lacks it.
        cases.applyStatement(listOf(case("c2", "S3|1|2")))

        val held = cases.list().associateBy { it.caseId }
        val released = assertNotNull(held["c1"], "the released case's row must be kept")
        assertFalse(released.assigned)
        assertNotNull(released.releasedSeenAt)
        assertEquals(1, released.submissions)
        assertEquals(draft, released.latestSubmissionId)
        assertTrue(held.getValue("c2").assigned)

        // The draft is untouched: still listed, still named with its case,
        // still pushable — its op is pending, not dropped.
        val summary = assertNotNull(store.getSubmission(draft))
        assertEquals("c1", summary.caseId)
        assertEquals("S3|1|1", summary.caseKey)
        assertEquals(false, summary.caseAssigned)
        assertEquals(1, summary.pendingOps)
        assertEquals("c1", store.pendingOps(10).single().caseId)
        assertEquals("S3|1|1", cases.caseKeyFor("c1"))
    }

    @Test
    fun `an empty statement releases everything and deletes nothing`() {
        val database = db()
        val cases = CaseStore(database)
        cases.applyStatement(listOf(case("c1", "S3|1|1"), case("c2", "S3|1|2")))
        cases.applyStatement(emptyList())
        assertEquals(2, cases.list().size)
        assertTrue(cases.list().none { it.assigned })
    }

    @Test
    fun `a case assigned back is assigned again, its release cleared, its row updated`() {
        val database = db()
        val cases = CaseStore(database)
        cases.applyStatement(listOf(case("c1", "S3|1|1")))
        cases.applyStatement(emptyList())
        cases.applyStatement(listOf(case("c1", "S3|1|1", head = "Amina B.")))
        val back = cases.get("c1")!!
        assertTrue(back.assigned)
        assertNull(back.releasedSeenAt)
        assertEquals("Amina B.", back.data["headName"])
        assertEquals("4", back.data["hhSize"])
    }

    @Test
    fun `there is no delete for cases anywhere in the generated queries`() {
        // The schema is the guarantee; this checks the generated surface says
        // the same. A query named deleteCase or clearCases would be the start
        // of the silent loss §4.3 forbids.
        val names = SyncQueries::class.java.methods.map { it.name.lowercase() }
        assertTrue(
            names.none { "case" in it && ("delete" in it || "clear" in it || "remove" in it) },
            "found a case-deleting query: ${names.filter { "case" in it }}",
        )
    }

    @Test
    fun `the refusal the push path can name is explained with the draft's fate`() {
        val text = RejectReasons.describe(RejectReasons.NOT_ASSIGNED, 3)
        assertTrue("no longer assigned to you" in text, text)
        assertTrue("kept on this device" in text, text)
        assertEquals("2 ops rejected: something_new", RejectReasons.describe("something_new", 2))
    }
}
