package com.amr.data_collection_lab

import android.app.Activity
import android.os.Bundle
import android.util.Log
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory
import com.dcp.core.sync.DatasetBenchmark
import com.dcp.core.sync.DatasetStore
import com.dcp.core.sync.openDatabase
import java.io.File
import kotlin.concurrent.thread

/**
 * What a real dataset costs on a real phone (Form IR §3.2, §12).
 *
 * Debug builds only. `scripts/measure_datasets_on_device.sh` launches it and
 * reads the figures out of logcat.
 *
 * The numbers matter more than the mechanism. §3.2 states a performance
 * contract — resolution proportional to the rows matching the selector — and
 * `StoredDatasetSource` currently reads a whole version out of SQLCipher and
 * filters in memory. Whether that is good enough is not a question a laptop can
 * answer: the target is a 2 GB handset holding 38,000 villages, and if
 * per-keystroke filtering is not viable there then the honest outcome is a
 * stated limit and an index, not a feature called done.
 *
 * It runs against the app's **real** SQLCipher database, through the same
 * keystore-derived key (§14). Measuring an unencrypted scratch file would be
 * measuring something the product does not do.
 */
class BenchmarkActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val rows = intent.getIntExtra("rows", 38_000)
        val districts = intent.getIntExtra("districts", 180)

        // Off the main thread: 38,000 rows through SQLCipher is seconds, and an
        // ANR would end the measurement rather than report it.
        thread {
            val tag = "DCP_BENCH"
            try {
                val database = openDatabase(
                    DatabaseDriverFactory(applicationContext),
                    DatabaseKeyStore(requireUserAuthentication = AppLock.ENABLED),
                )
                val file = File(applicationContext.getDatabasePath("dcp.db").absolutePath)
                val runtime = Runtime.getRuntime()

                Log.i(tag, "START rows=$rows districts=$districts")
                val results = DatasetBenchmark.run(
                    store = DatasetStore(database),
                    rows = rows,
                    districts = districts,
                    // The file on disk, including SQLCipher's page overhead —
                    // what the device's storage actually gives up.
                    onDatabaseBytes = {
                        listOf("dcp.db", "dcp.db-wal", "dcp.db-shm")
                            .sumOf { File(file.parentFile, it).length() }
                    },
                    onHeapBytes = {
                        // After a GC, so this is what the cache is holding
                        // rather than what has not been collected yet.
                        runtime.gc()
                        runtime.totalMemory() - runtime.freeMemory()
                    },
                    log = { Log.i(tag, it) },
                )
                results.forEach { Log.i(tag, "RESULT $it") }
                Log.i(tag, "DONE")
            } catch (e: Throwable) {
                Log.e(tag, "FAILED ${e::class.simpleName}: ${e.message}", e)
                Log.i(tag, "DONE")
            } finally {
                finish()
            }
        }
    }
}
