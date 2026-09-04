package com.amr.data_collection_lab

import android.app.Activity
import android.net.TrafficStats
import android.os.Bundle
import android.util.Log
import com.amr.data_collection_lab.collection.AppGraph
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory
import com.dcp.core.sync.DatasetBenchmark
import com.dcp.core.sync.DatasetStore
import com.dcp.core.sync.openDatabase
import java.io.File
import kotlin.concurrent.thread
import kotlin.time.ExperimentalTime
import kotlin.time.TimeSource
import kotlinx.coroutines.runBlocking

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
        val serverUrl = intent.getStringExtra("serverUrl")

        thread {
            val tag = "DCP_BENCH"
            try {
                if (serverUrl != null) {
                    syncBenchmark(tag, serverUrl)
                    return@thread
                }
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

    /**
     * The acceptance, and the numbers that go with it.
     *
     * Points this device at a real server, syncs, and drives the real engine
     * over whatever arrived. Everything here is the shipping path — the same
     * `AppGraph` the app builds, the same `SyncClient`, the same SQLCipher
     * database, the same `StoredDatasetSource`. A benchmark over a scratch file
     * would measure something the product does not do.
     */
    @OptIn(ExperimentalTime::class)
    private fun syncBenchmark(tag: String, serverUrl: String) {
        val mark = TimeSource.Monotonic
        val graph = AppGraph(
            DatabaseDriverFactory(applicationContext),
            DatabaseKeyStore(requireUserAuthentication = AppLock.ENABLED),
        )
        val db = File(applicationContext.getDatabasePath("dcp.db").absolutePath)
        fun bytes() = listOf("dcp.db", "dcp.db-wal", "dcp.db-shm")
            .sumOf { File(db.parentFile, it).length() }

        Log.i(tag, "START sync $serverUrl")
        when (val set = graph.serverConfig.setBaseUrl(serverUrl)) {
            is com.dcp.core.sync.ServerUrlResult.Invalid ->
                Log.i(tag, "  refused the address: ${set.reason}")
            is com.dcp.core.sync.ServerUrlResult.Valid ->
                Log.i(tag, "  server: ${set.url}")
        }

        val before = bytes()
        // What actually came over the air, counted by the kernel for this uid.
        // Server-side content-length would miss headers and every retry; this
        // is the number a field connection is billed for.
        val rxBefore = TrafficStats.getUidRxBytes(android.os.Process.myUid())
        val txBefore = TrafficStats.getUidTxBytes(android.os.Process.myUid())
        val started = mark.markNow()
        val result = runBlocking { graph.syncClient.syncOnce() }
        val elapsed = started.elapsedNow()
        val rx = TrafficStats.getUidRxBytes(android.os.Process.myUid()) - rxBefore
        val tx = TrafficStats.getUidTxBytes(android.os.Process.myUid()) - txBefore

        Log.i(tag, "RESULT sync_wall_ms=${elapsed.inWholeMilliseconds}ms")
        Log.i(tag, "RESULT sync_rx_mb=${rx / 1_048_576.0}MB")
        Log.i(tag, "RESULT sync_tx_kb=${tx / 1024.0}kB")
        Log.i(tag, "RESULT forms_fetched=${result.fetchedForms}")
        Log.i(tag, "RESULT dataset_rows_fetched=${result.fetchedDatasetRows}")
        Log.i(tag, "RESULT db_growth_mb=${(bytes() - before) / 1_048_576.0}MB")
        result.error?.let { Log.i(tag, "  sync error: $it") }
        result.formError?.let { Log.i(tag, "  form error: $it") }
        result.datasetError?.let { Log.i(tag, "  dataset error: $it") }

        val held = graph.formStore.all()
        Log.i(tag, "  forms held: " + held.joinToString { "${it.formId} v${it.version}" })
        graph.datasetStore.all().forEach {
            Log.i(
                tag,
                "  dataset ${it.datasetKey} v${it.version} ${it.rowCount} rows " +
                    "complete=${it.complete} indexed=${it.filterColumns}",
            )
        }

        val form = held.firstOrNull { it.formId == "ucl_cascade" }
        if (form == null) {
            Log.i(tag, "  no ucl_cascade form delivered; nothing to drive")
        } else {
            DatasetBenchmark.driveCascade(
                store = graph.datasetStore,
                formVersionId = form.formVersionId,
                irJson = form.irJson,
                log = { Log.i(tag, it) },
            )
        }
        Log.i(tag, "DONE")
    }
}
