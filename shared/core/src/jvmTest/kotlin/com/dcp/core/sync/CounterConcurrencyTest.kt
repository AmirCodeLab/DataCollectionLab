package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.form.FormValue
import java.io.File
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking

class CounterConcurrencyTest {

    /**
     * The counter must be monotonic and unique under concurrent appends — the
     * bump and the insert have to sit in ONE transaction. Guards the exact
     * failure mode where the bump moves outside the transaction: two threads
     * bump, both read the same counter, and either two ops share a counter
     * (corrupting LWW ordering) or the unique index rejects one insert.
     *
     * Uses a file database: each thread gets its own connection, like separate
     * writers would. The in-memory JDBC driver shares one connection and would
     * serialise everything, proving nothing.
     */
    @Test
    fun `concurrent appends never duplicate or skip a counter`() {
        val dbFile = File.createTempFile("dcp-concurrency", ".db").apply { deleteOnExit() }
        val properties = Properties().apply {
            setProperty("busy_timeout", "10000") // writers wait, not fail, on lock contention
        }
        val driver =
            JdbcSqliteDriver("jdbc:sqlite:${dbFile.absolutePath}", properties, DcpDatabase.Schema)
        val store = SubmissionStore(DcpDatabase(driver))
        val submissionId = store.createDraft("f", 1)

        val workers = 8
        val opsPerWorker = 25
        val ops = runBlocking {
            (1..workers).map { worker ->
                async(Dispatchers.IO) {
                    (1..opsPerWorker).map { i ->
                        store.appendOp(
                            submissionId, "f", 1, OpKind.SET,
                            path = "q$worker", value = FormValue.Integer(i.toLong()),
                        )
                    }
                }
            }.awaitAll().flatten()
        }

        val total = workers * opsPerWorker
        val counters = ops.map { it.counter }
        assertEquals(total, counters.size, "every append must return")
        assertEquals(total, counters.distinct().size, "no two ops may share a counter")
        assertEquals((1L..total).toList(), counters.sorted(), "no counter may be skipped")
        assertEquals(total, store.opsFor(submissionId).size, "no duplicate rows written")
    }
}
