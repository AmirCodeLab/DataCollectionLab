package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.form.FormValue
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class SubmissionStoreTest {

    private fun store(): SubmissionStore {
        val driver = JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        return SubmissionStore(DcpDatabase(driver))
    }

    @Test
    fun `counter is monotonic across ops`() {
        val store = store()
        val id = store.createDraft("f", 1)
        val counters = (1..5).map {
            store.appendOp(id, "f", 1, OpKind.SET, "age", FormValue.Integer(it.toLong())).counter
        }
        assertEquals(counters.sorted(), counters)
        assertEquals(counters.distinct().size, counters.size)
        assertEquals(5, counters.size)
    }

    @Test
    fun `ops fold to last writer, unset removes`() {
        val store = store()
        val id = store.createDraft("f", 1)
        store.appendOp(id, "f", 1, OpKind.SET, "name", FormValue.Text("a"))
        store.appendOp(id, "f", 1, OpKind.SET, "name", FormValue.Text("b"))
        store.appendOp(id, "f", 1, OpKind.SET, "age", FormValue.Integer(30))
        store.appendOp(id, "f", 1, OpKind.UNSET, "age")
        store.appendOp(id, "f", 1, OpKind.SET, "height", FormValue.Decimal(1.75))
        store.appendOp(id, "f", 1, OpKind.SET, "dob", FormValue.DateValue("1990-01-01"))

        // A date folds back as Text — the IR represents dates as YYYY-MM-DD
        // strings and the engine compares them as ISO text (spec §2.1).
        assertEquals(
            mapOf(
                "name" to FormValue.Text("b"),
                "height" to FormValue.Decimal(1.75),
                "dob" to FormValue.Text("1990-01-01"),
            ),
            store.materialisedAnswers(id),
        )
    }

    @Test
    fun `date and text round-trip through value json`() {
        val store = store()
        val id = store.createDraft("f", 1)
        store.appendOp(id, "f", 1, OpKind.SET, "dob", FormValue.DateValue("2000-02-29"))
        // DateValue serialises as a string; the fold reads it back as Text — the
        // engine's set() accepts either because comparison happens on iso text.
        val folded = store.materialisedAnswers(id).getValue("dob")
        assertTrue(folded is FormValue.Text || folded is FormValue.DateValue)
    }

    @Test
    fun `finalize op flips status and shows in pending count`() {
        val store = store()
        val id = store.createDraft("f", 1)
        store.appendOp(id, "f", 1, OpKind.SET, "name", FormValue.Text("x"))
        store.appendOp(id, "f", 1, OpKind.FINALIZE)
        val summary = store.getSubmission(id)!!
        assertEquals(SubmissionStatus.FINALIZED, summary.status)
        assertEquals(2, summary.pendingOps)
    }
}
