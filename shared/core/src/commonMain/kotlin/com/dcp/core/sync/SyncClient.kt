package com.dcp.core.sync

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.delay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull

data class SyncConfig(
    /** Sync protocol §4: batches are bounded, default 500 ops. */
    val batchSize: Int = 500,
    val pullLimit: Int = 200,
    val maxAttempts: Int = 4,
    val baseDelayMs: Long = 1_000,
    val maxDelayMs: Long = 30_000,
)

/** What this installation reports about itself when registering (sync §4). */
data class DeviceInfo(
    /** One of the server's platform values: android, ios, desktop, web. */
    val platform: String = "desktop",
    val osVersion: String? = null,
    val appVersion: String? = null,
)

data class SyncResult(
    val pushedOps: Int,
    val rejectedOps: Int,
    val pulledOps: Int,
    val error: String? = null,
) {
    val isSuccess: Boolean get() = error == null
}

/**
 * Talks to /api/v1/sync. Push drains the op outbox in bounded batches; an op
 * leaves the outbox ONLY when the server acknowledges its opId, so a failed or
 * interrupted push never loses an op, and replaying one is idempotent
 * server-side (sync §4) — never a duplicate. Pull resumes from the locally
 * persisted cursor, which advances only after a batch is durably written
 * (sync §5).
 *
 * Failures are recorded, never thrown: field devices sync opportunistically
 * and the outbox simply stays pending until a sync succeeds.
 */
class SyncClient(
    private val store: SubmissionStore,
    private val baseUrl: String,
    private val config: SyncConfig = SyncConfig(),
    private val deviceInfo: DeviceInfo = DeviceInfo(),
    httpClient: HttpClient? = null,
) {
    private val http: HttpClient = httpClient ?: HttpClient(CIO) {
        expectSuccess = true
        install(ContentNegotiation) { json(SyncJson) }
    }

    suspend fun syncOnce(): SyncResult {
        var pushed = 0
        var rejected = 0
        var pulled = 0
        return try {
            // The server rejects every op from a device it has never seen, so
            // an unregistered install must introduce itself before its first
            // push. Registration is idempotent: "already registered" is a 2xx
            // success, and only a server acknowledgement sets the local flag.
            if (!store.isDeviceRegistered()) {
                withRetry { registerDevice() }
                store.markDeviceRegistered()
            }

            // Give ops rejected on an earlier sync another chance — a
            // rejection can be transient (form published late, device
            // authorized after the fact).
            store.requeueRejectedOps()

            while (true) {
                val batch = store.pendingOps(config.batchSize)
                if (batch.isEmpty()) break
                val response = withRetry { pushBatch(batch) }

                val batchIds = batch.map { it.opId }.toSet()
                val accepted = response.accepted.filter { it in batchIds }
                val rejectedOps = response.rejected
                    .filter { it.opId != null && it.opId in batchIds }
                    .map { RejectedPush(it.opId!!, it.reason) }
                store.markPushResult(accepted, rejectedOps)
                pushed += accepted.size
                rejected += rejectedOps.size

                if (accepted.isEmpty() && rejectedOps.isEmpty()) {
                    // The server answered but resolved none of our ops; retrying
                    // the same batch forever would spin.
                    error("push made no progress on a batch of ${batch.size} ops")
                }
            }

            do {
                val page = withRetry { pullPage(store.syncStatus().pullCursor) }
                store.applyPullBatch(page.ops.map { it.toSyncOp() }, page.nextCursor)
                pulled += page.ops.size
            } while (page.hasMore)

            store.recordSyncSuccess()
            SyncResult(pushed, rejected, pulled)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val message = e.message ?: "sync failed"
            store.recordSyncError(message)
            SyncResult(pushed, rejected, pulled, error = message)
        }
    }

    private suspend fun registerDevice(): WireDeviceRegisterResponse =
        http.post("$baseUrl/api/v1/devices") {
            contentType(ContentType.Application.Json)
            setBody(
                WireDeviceRegisterRequest(
                    deviceId = store.deviceId,
                    platform = deviceInfo.platform,
                    osVersion = deviceInfo.osVersion,
                    appVersion = deviceInfo.appVersion,
                )
            )
        }.body()

    private suspend fun pushBatch(batch: List<SyncOp>): WirePushResponse =
        http.post("$baseUrl/api/v1/sync/push") {
            contentType(ContentType.Application.Json)
            setBody(WirePushRequest(store.deviceId, batch.map { it.toWire() }))
        }.body()

    private suspend fun pullPage(cursor: Long): WirePullResponse =
        http.get("$baseUrl/api/v1/sync/pull") {
            parameter("cursor", cursor)
            parameter("limit", config.pullLimit)
        }.body()

    /** Exponential backoff; the last failure propagates to syncOnce's catch. */
    private suspend fun <T> withRetry(block: suspend () -> T): T {
        var attempt = 0
        while (true) {
            try {
                return block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                attempt++
                if (attempt >= config.maxAttempts) throw e
                val backoff = (config.baseDelayMs shl (attempt - 1)).coerceAtMost(config.maxDelayMs)
                delay(backoff)
            }
        }
    }

    private fun SyncOp.toWire() = WireOp(
        opId = opId,
        submissionId = submissionId,
        formId = formId,
        formVersion = formVersion,
        kind = kind,
        path = path,
        value = valueJson?.let { Json.parseToJsonElement(it) },
        deviceId = deviceId,
        actorId = actorId,
        counter = counter,
        wallClock = wallClock,
    )

    private fun WirePulledOp.toSyncOp() = SyncOp(
        opId = opId,
        submissionId = submissionId,
        formId = formId,
        formVersion = formVersion,
        kind = kind,
        path = path,
        valueJson = value?.takeUnless { it is JsonNull }?.toString(),
        deviceId = deviceId,
        actorId = actorId ?: "unknown",
        counter = counter,
        wallClock = wallClock,
        synced = true,
    )
}
