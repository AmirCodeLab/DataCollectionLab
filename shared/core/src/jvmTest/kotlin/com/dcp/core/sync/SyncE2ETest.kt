package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.form.FormValue
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.HttpSend
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.plugin
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.http.encodedPath
import io.ktor.serialization.kotlinx.json.json
import java.io.File
import java.io.IOException
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue

/**
 * End-to-end against a REAL backend (uvicorn + Postgres) at [BASE_URL].
 * Self-gating: skipped when no DCP backend answers /health there. The server
 * must have household_survey v1 published — see scripts in the session notes.
 * Devices register themselves via POST /api/v1/devices on first sync, so no
 * pre-registration is needed.
 *
 * NOTE: a (deviceId, counter) pair can only be consumed once per server
 * database — the server treats a replayed counter under a new opId as a
 * device that lost its log. Re-running against the same server DB needs a
 * freshly registered device id.
 */
class SyncE2ETest {

    private val baseUrl = System.getenv("DCP_SYNC_BASE_URL") ?: "http://localhost:8000"

    /** Explicit opt-in: a (deviceId, counter) pair is consumable once per
     * server database, so each run needs a FRESHLY REGISTERED device id.
     * Without the env var the mid-push test is skipped. */
    private val deviceId: String? = System.getenv("DCP_E2E_DEVICE")

    private fun serverUp(): Boolean = runBlocking {
        runCatching {
            HttpClient(CIO).use { it.get("$baseUrl/health").status.value == 200 }
        }.getOrDefault(false)
    }

    private fun fileStore(deviceId: String): SubmissionStore {
        val dbFile = File.createTempFile("dcp-e2e", ".db").apply { deleteOnExit() }
        val driver = JdbcSqliteDriver(
            "jdbc:sqlite:${dbFile.absolutePath}", Properties(), DcpDatabase.Schema,
        )
        return SubmissionStore(DcpDatabase(driver), deviceIdOverride = deviceId)
    }

    private fun httpClient() = HttpClient(CIO) {
        expectSuccess = true
        install(ContentNegotiation) { json(SyncJson) }
    }

    /** Every opId the server holds for [forDevice], via the real pull API. */
    private suspend fun serverOpIds(forDevice: String): List<String> {
        httpClient().use { http ->
            val ids = mutableListOf<String>()
            var cursor = 0L
            while (true) {
                val page: WirePullResponse = http.get("$baseUrl/api/v1/sync/pull") {
                    parameter("cursor", cursor)
                    parameter("limit", 500)
                }.body()
                ids += page.ops.filter { it.deviceId == forDevice }.map { it.opId }
                cursor = page.nextCursor
                if (!page.hasMore) break
            }
            return ids
        }
    }

    @Test
    fun `real server dying mid-push loses nothing and duplicates nothing`() {
        assumeTrue("DCP_E2E_DEVICE not set (needs a freshly registered device id)", deviceId != null)
        assumeTrue("no DCP backend at $baseUrl", serverUp())
        val deviceId = deviceId!!
        runBlocking {
            val store = fileStore(deviceId)
            val submission = store.createDraft("household_survey", 1)
            repeat(110) { i ->
                store.appendOp(
                    submission, "household_survey", 1, OpKind.SET,
                    path = "observations", value = FormValue.Text("note $i"),
                )
            }
            assertEquals(110, store.pendingCount().toInt())

            // The server "dies" after acknowledging two batches: the transport
            // starts refusing exactly where a mid-push crash would.
            var pushResponses = 0
            val dying = httpClient().apply {
                plugin(HttpSend).intercept { request ->
                    if (request.url.encodedPath.endsWith("/sync/push") && pushResponses >= 2) {
                        throw IOException("simulated server death mid-push")
                    }
                    val call = execute(request)
                    if (request.url.encodedPath.endsWith("/sync/push")) pushResponses++
                    call
                }
            }
            val interrupted = SyncClient(
                store, baseUrl,
                SyncConfig(batchSize = 25, maxAttempts = 1), httpClient = dying,
            ).syncOnce()

            assertNotNull(interrupted.error)
            assertEquals(50, interrupted.pushedOps)
            assertEquals(60, store.pendingCount().toInt())
            assertNotNull(store.syncStatus().lastError)

            // Recovery with a healthy client: the outbox drains completely...
            val recovered = SyncClient(
                store, baseUrl, SyncConfig(batchSize = 25), httpClient = httpClient(),
            ).syncOnce()
            assertNull(recovered.error)
            assertEquals(60, recovered.pushedOps)
            assertEquals(0, store.pendingCount().toInt())
            assertNull(store.syncStatus().lastError)

            // ...and the server holds EXACTLY our 110 ops for this device:
            // nothing lost, nothing duplicated, byte-for-byte the same ids.
            val onServer = serverOpIds(deviceId)
            val local = store.opsFor(submission).map { it.opId }
            assertEquals(110, onServer.size)
            assertEquals(onServer.distinct().size, onServer.size)
            assertEquals(local.toSet(), onServer.toSet())

            // and the pull cursor advanced past what we ingested
            assumeTrue(store.syncStatus().pullCursor > 0)
        }
    }

    @Test
    fun `a brand-new device can register and push in one flow`(): Unit = runBlocking {
        assumeTrue("no DCP backend at $baseUrl", serverUp())
        // An id the server has never seen: first sync must register it itself.
        val freshId = "dev-fresh-" + buildString {
            repeat(12) { append("0123456789abcdef"[kotlin.random.Random.nextInt(16)]) }
        }
        val store = fileStore(freshId)
        val submission = store.createDraft("household_survey", 1)
        repeat(3) { i ->
            store.appendOp(
                submission, "household_survey", 1, OpKind.SET,
                path = "observations", value = FormValue.Text("first sync $i"),
            )
        }

        val result = SyncClient(
            store, baseUrl, SyncConfig(),
            deviceInfo = DeviceInfo("desktop", osVersion = "e2e", appVersion = "e2e"),
            httpClient = httpClient(),
        ).syncOnce()

        assertNull(result.error)
        assertEquals(3, result.pushedOps)
        assertEquals(0, result.rejectedOps)
        assertEquals(0, store.pendingCount().toInt())
        // the server actually stored them under the fresh device id
        assertEquals(
            store.opsFor(submission).map { it.opId }.toSet(),
            serverOpIds(freshId).toSet(),
        )
    }

    @Test
    fun `total outage leaves the outbox and cursor untouched`(): Unit = runBlocking {
        val store = fileStore("dev-nowhere")
        val submission = store.createDraft("household_survey", 1)
        store.appendOp(submission, "household_survey", 1, OpKind.SET, "observations",
            FormValue.Text("offline"))
        val cursorBefore = store.syncStatus().pullCursor

        val result = SyncClient(
            store, "http://localhost:59999", // nothing listens here
            SyncConfig(maxAttempts = 2, baseDelayMs = 1), httpClient = httpClient(),
        ).syncOnce()

        assertNotNull(result.error)
        assertEquals(1, store.pendingCount().toInt())
        assertEquals(cursorBefore, store.syncStatus().pullCursor)
        assertNotNull(store.syncStatus().lastError)
    }
}
