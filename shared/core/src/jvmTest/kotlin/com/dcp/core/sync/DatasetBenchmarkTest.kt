package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.io.File
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * The benchmark, on a laptop, so it is known to run before it is asked of a
 * phone — and so the two numbers can be put beside each other.
 *
 * It asserts almost nothing. The figures are the input to a decision (§3.2's
 * performance contract) and not the output of one, and a threshold asserted
 * here would be a laptop's opinion about a handset. The only assertion is that
 * the work actually happened: a benchmark that measured nothing would report
 * excellent numbers.
 *
 * The scale is small on purpose — the full 38,000 rows belong on the device,
 * where the answer matters. `scripts/measure_datasets_on_device.sh` is that.
 */
class DatasetBenchmarkTest {

    @Test
    fun `the benchmark runs and reports every figure it claims to`() {
        val file = File.createTempFile("dcp-bench", ".db").also { it.delete() }
        try {
            val driver = JdbcSqliteDriver("jdbc:sqlite:${file.absolutePath}", Properties())
            DcpDatabase.Schema.create(driver)
            val store = DatasetStore(DcpDatabase(driver))

            val results = DatasetBenchmark.run(
                store = store,
                rows = 5_000,
                districts = 180,
                onDatabaseBytes = { file.length() },
                log = { println(it) },
            )
            results.forEach { println("  $it") }

            val names = results.map { it.name }.toSet()
            for (owed in listOf(
                "first_sync_write_ms", "db_growth_mb", "filter_median_ms",
                "filter_p95_ms", "delta_apply_ms",
            )) {
                assertTrue(owed in names, "the benchmark did not report $owed")
            }
            assertTrue(
                results.single { it.name == "first_sync_write_ms" }.value > 0,
                "a benchmark that measured nothing would report excellent numbers",
            )
        } finally {
            file.delete()
        }
    }
}
