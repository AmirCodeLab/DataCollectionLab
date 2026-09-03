package com.dcp.core.sync

import com.dcp.core.crypto.Hex
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.expectSuccess
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.serialization.kotlinx.json.json
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.delay
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.JsonElement
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
    /** Server's reason when registration was refused; null for other failures. */
    val registrationFailure: String? = null,
    /** Media files the server sealed this pass (sync §9). */
    val uploadedMedia: Int = 0,
    /** Files still staged — still uploading, or refused and being retried. */
    val pendingMedia: Long = 0,
    /** Form versions fetched this pass (sync §5) — new or newly redeployed. */
    val fetchedForms: Int = 0,
    /**
     * Why the form manifest could not be applied, or null. Separate from
     * [error] because it does not fail the sync: the answers are what a sync
     * exists to move, and a device that could not refresh its forms still holds
     * the ones it had.
     */
    val formError: String? = null,
    /** Dataset rows fetched this pass (sync §5, `scope=datasets`). */
    val fetchedDatasetRows: Int = 0,
    /**
     * Why the reference data could not be brought up to date, or null.
     *
     * Separate from [formError] and reported even when everything else
     * succeeded, because this is the failure with no other symptom: a device
     * holding last month's village list collects perfectly, syncs perfectly,
     * and files answers against places that no longer exist. There is nothing
     * on any screen to notice. This sentence is the whole of the noticing.
     */
    val datasetError: String? = null,
) {
    val isSuccess: Boolean get() = error == null
}

/**
 * The server refused to register this device. [reason] is its machine-readable
 * code (project_not_found, project_ambiguous, project_mismatch,
 * device_revoked) and is null only when the response carried no structured
 * body — a proxy error page, say.
 */
class DeviceRegistrationException(
    val reason: String?,
    val statusCode: Int,
    val detail: String,
) : Exception(
    "device registration refused: ${reason ?: "HTTP $statusCode"} — $detail",
)

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
    /**
     * Where the server is — the configuration itself, not an address and not a
     * supplier of one.
     *
     * **The caller does not get to say what the address is, and that is the
     * point.** This took `() -> String` first, and the lambda is exactly wide
     * enough to express the mistake it was meant to prevent: the app's own
     * wiring passed `{ defaultSyncBaseUrl() }` — the compile-time constant —
     * and every one of the 264 tests in this repository passed while the
     * settings screen said "Saved. The next sync will use this address" and
     * the sync went somewhere else. On a handset that meant zero requests
     * reaching the server whose address had just been entered.
     *
     * The same shape as the form-version fix (`FormCatalog`, break 30): the way
     * to stop a caller choosing wrongly is to stop it choosing. There is now
     * one object that knows the address, and passing anything else means
     * constructing a second [ServerConfig] beside the real one.
     *
     * Read **once per sync**, not once per request — see [syncOnce].
     */
    private val serverConfig: ServerConfig,
    private val config: SyncConfig = SyncConfig(),
    private val deviceInfo: DeviceInfo = DeviceInfo(),
    httpClient: HttpClient? = null,
    /**
     * Which fields each form version marks `sensitive`, for `field_level` mode.
     * The default knows no form, which makes the encryptor fail closed and
     * encrypt every value rather than guess that a field is safe to send in the
     * clear (see [FormSensitivity]).
     */
    formSensitivity: FormSensitivity = FormSensitivity { _, _ -> null },
    /**
     * Uploads staged media (sync §9). Null on a client with no media staging —
     * the desktop review app — where the sync loop is ops only.
     */
    private val media: com.dcp.core.media.MediaUploader? = null,
    /**
     * Where delivered form versions are kept (sync §5). Null on a client that
     * does not collect, where asking the server for forms would be work with
     * nothing to do.
     */
    private val forms: FormStore? = null,
    private val datasets: DatasetStore? = null,
) {
    private val http: HttpClient = httpClient ?: HttpClient(CIO) {
        expectSuccess = true
        install(ContentNegotiation) { json(SyncJson) }
    }

    private val crypto = SyncCrypto(store, formSensitivity)

    /**
     * Is there a DCP server at [url], and which deployment is it?
     *
     * Separate from [syncOnce] because it answers a different question and a
     * person asking it is in a different situation: they have just typed an
     * address and want to know whether it is right, before any data moves. A
     * sync would answer it too, eventually, but it registers the device,
     * refreshes crypto and pushes the outbox first, and a failure anywhere in
     * that chain reads as "the address is wrong" whether or not it is.
     *
     * `GET /health` and nothing else: it is the one endpoint that needs no
     * device, no project and no authorisation, so a failure here is about
     * reachability alone. It also returns the server's environment name, which
     * is the cheapest way to catch the mistake this cannot otherwise see — an
     * address that connects perfectly to the wrong server.
     */
    suspend fun checkConnection(url: String = serverConfig.baseUrl()): ConnectionCheck = try {
        val response = http.get("$url/health") { expectSuccess = false }
        if (!response.status.isSuccess()) {
            ConnectionCheck.Failed(
                url,
                "$url answered with HTTP ${response.status.value}. Something is at that " +
                    "address, but it is not answering as a DCP server.",
            )
        } else {
            val body: WireHealth = response.body()
            ConnectionCheck.Reached(url, body.environment)
        }
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        // Any failure, including a body that would not decode: a server that
        // answers /health with something else is not one this app can use, and
        // saying so is more useful than a parse error.
        ConnectionCheck.Failed(url, SyncFailure.describe(url, e))
    }

    suspend fun syncOnce(): SyncResult {
        var pushed = 0
        var rejected = 0
        var pulled = 0
        var uploadedMedia = 0
        var fetchedForms = 0
        var formError: String? = null
        var fetchedDatasetRows = 0
        var datasetError: String? = null
        // Read once, here, and used for every request in this pass.
        //
        // Not per request, and the reason is not tidiness. `refreshCrypto`
        // caches the recipient set of the project the *server* names, and the
        // push that follows encrypts to it. If the address changed between the
        // two, this device would wrap content keys to one server's project keys
        // and hand the ciphertext to a different server — which stores it,
        // reports success, and is holding answers only a third party's private
        // key can ever open. Reading once makes that unreachable rather than
        // unlikely.
        //
        // It is also what the failure message reports, so a sync that failed
        // against the old address cannot name the new one.
        val base = serverConfig.baseUrl()
        return try {
            // The server rejects every op from a device it has never seen, so
            // an unregistered install must introduce itself before its first
            // push. Registration is idempotent: "already registered" is a 2xx
            // success, and only a server acknowledgement sets the local flag.
            if (!store.isDeviceRegistered()) {
                withRetry { registerDevice(base) }
                store.markDeviceRegistered()
            }

            // Before anything is pushed, never after: an op that should have
            // been encrypted cannot be recalled once it has left in the clear.
            // Rotation (envelope §8) also adds recipients, so this is refreshed
            // every sync rather than cached from registration.
            withRetry { refreshCrypto(base) }

            // Give ops rejected on an earlier sync another chance — a
            // rejection can be transient (form published late, device
            // authorized after the fact).
            store.requeueRejectedOps()

            while (true) {
                val batch = store.pendingOps(config.batchSize)
                if (batch.isEmpty()) break
                // Encrypt here rather than in the retry block: the nonce is
                // derived from (deviceId, counter), so re-encrypting produces
                // identical bytes, but doing the work once is simply cheaper.
                val prepared = crypto.prepare(batch)
                val response = withRetry { pushBatch(base, prepared) }

                val batchIds = batch.map { it.opId }.toSet()
                val accepted = response.accepted.filter { it in batchIds }
                val rejectedOps = response.rejected
                    .filter { it.opId != null && it.opId in batchIds }
                    .map { RejectedPush(it.opId!!, it.reason) }
                store.markPushResult(accepted, rejectedOps)
                markUploadedKeys(prepared, accepted.toSet())
                pushed += accepted.size
                rejected += rejectedOps.size

                if (accepted.isEmpty() && rejectedOps.isEmpty()) {
                    // The server answered but resolved none of our ops; retrying
                    // the same batch forever would spin.
                    error("push made no progress on a batch of ${batch.size} ops")
                }
            }

            // The manifest rides the first pull page only. It is a complete
            // statement of what this device's environment deploys rather than a
            // delta (sync §5), so one copy is the whole answer and asking again
            // on page two would be paying twice for it.
            // Null until the first page answers; still null afterwards if the
            // server said nothing about forms at all. See WirePullResponse.
            var manifest: List<WireDeployedFormVersion>? = null
            var datasetManifest: List<WireDeployedDatasetVersion>? = null
            var first = true
            do {
                val page = withRetry {
                    pullPage(
                        base,
                        store.syncStatus().pullCursor,
                        wantForms = first && forms != null,
                        wantDatasets = first && datasets != null,
                    )
                }
                if (first) {
                    manifest = page.forms
                    datasetManifest = page.datasets
                    first = false
                }
                store.applyPullBatch(page.ops.map { it.toSyncOp() }, page.nextCursor)
                pulled += page.ops.size
            } while (page.hasMore)

            // After the ops, and non-fatally, for the same reason media is: the
            // answers are the small irreplaceable part and they are already
            // safe by here. A device that could not refresh its forms keeps the
            // ones it has and stays able to collect, which is what offline-first
            // means when the failure is the server's rather than the network's.
            forms?.let { store ->
                try {
                    val refresh = refreshForms(base, store, manifest)
                    fetchedForms = refresh.fetched
                    if (refresh.undelivered.isNotEmpty()) {
                        formError = "could not download " +
                            refresh.undelivered.joinToString(", ") +
                            " from $base — the manifest lists it but the document " +
                            "would not fetch"
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    formError = e.message ?: "form sync failed"
                }
            }

            // After the forms, and it has to be: what a device must hold is
            // derived from the form versions deployed to it, so refreshing
            // datasets first would be answering a question whose inputs had not
            // arrived. Non-fatal for the same reason forms are — a device that
            // could not fetch a village list keeps the one it had and can still
            // collect — except that it says so, loudly, because this is the
            // failure nothing else can see.
            datasets?.let { store ->
                try {
                    val refresh = refreshDatasets(base, store, datasetManifest)
                    fetchedDatasetRows = refresh.rows
                    if (refresh.incomplete.isNotEmpty()) {
                        datasetError = "reference data is out of date on this device: " +
                            refresh.incomplete.joinToString(", ") +
                            " did not finish downloading from $base. Forms using " +
                            "those lists will not offer them until it does."
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    datasetError = e.message ?: "dataset sync failed"
                }
            }

            // Media last, and deliberately so. An op referencing a file the
            // server has never seen is accepted and marked pending (sync §9),
            // so ops-first costs nothing and gets the answers — the small,
            // cheap, irreplaceable part — off the device first. A 3 MB
            // photograph that takes four attempts across a week must never be
            // what holds up a questionnaire.
            //
            // Media failures do not fail the sync, for the same reason: the
            // answers are already safe, the file is still staged, and the next
            // pass resumes it from the chunk it reached.
            media?.let { uploader ->
                uploader.refreshPolicy()
                uploadedMedia = uploader.uploadPending().filesCompleted
            }

            store.recordSyncSuccess()
            SyncResult(
                pushed, rejected, pulled,
                uploadedMedia = uploadedMedia,
                pendingMedia = media?.let { it.pendingCount() } ?: 0,
                fetchedForms = fetchedForms,
                formError = formError,
                fetchedDatasetRows = fetchedDatasetRows,
                datasetError = datasetError,
            )
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Names the address that was tried and a cause in plain words;
            // the platform exception text is kept inside it, never instead
            // of it. See SyncFailure.
            val message = SyncFailure.describe(base, e)
            store.recordSyncError(message)
            SyncResult(
                pushed, rejected, pulled,
                error = message,
                registrationFailure = (e as? DeviceRegistrationException)?.reason,
                uploadedMedia = uploadedMedia,
                pendingMedia = media?.let { it.pendingCount() } ?: 0,
                fetchedForms = fetchedForms,
                formError = formError,
                fetchedDatasetRows = fetchedDatasetRows,
                datasetError = datasetError,
            )
        }
    }

    /**
     * Introduces this device to the server. A refusal is reported with the
     * server's own machine-readable reason and advice — "device registration
     * refused: project_not_found — ... Run scripts/seed_dev.py ..." — because
     * "invalid 409" tells a field engineer nothing about what to fix.
     */
    private suspend fun registerDevice(baseUrl: String): WireDeviceRegisterResponse {
        val response = http.post("$baseUrl/api/v1/devices") {
            // expectSuccess would throw before the body could be read, and the
            // body is the whole point of this call's error path.
            expectSuccess = false
            contentType(ContentType.Application.Json)
            setBody(
                WireDeviceRegisterRequest(
                    deviceId = store.deviceId,
                    platform = deviceInfo.platform,
                    osVersion = deviceInfo.osVersion,
                    appVersion = deviceInfo.appVersion,
                )
            )
        }
        if (response.status.isSuccess()) return response.body()

        val raw = runCatching { response.bodyAsText() }.getOrDefault("")
        val detail = runCatching { SyncJson.decodeFromString<WireErrorBody>(raw).detail }
            .getOrNull()
        throw DeviceRegistrationException(
            reason = detail?.reason,
            statusCode = response.status.value,
            detail = detail?.message?.takeIf { it.isNotBlank() }
                ?: raw.takeIf { it.isNotBlank() }
                ?: response.status.description,
        )
    }

    /**
     * Caches this project's security mode and recipient set (sync §4).
     *
     * A failure here falls back to the cached config, because offline-first is
     * a constraint: a device may go two weeks without a server and must keep
     * collecting and encrypting throughout. A device that has NEVER fetched one
     * is the only case that cannot be resolved locally — it does not know
     * whether this project encrypts — so it refuses to push rather than risk
     * sending an answer in the clear that the mode says must not be.
     */
    private suspend fun refreshCrypto(baseUrl: String) {
        val fetched = try {
            fetchCrypto(baseUrl)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (store.projectCrypto() != null) return
            throw e
        }
        if (fetched != null) store.putProjectCrypto(fetched)
    }

    /**
     * Null when the server answers 404: either it predates encryption support,
     * in which case it cannot store ciphertext and plaintext is the only
     * possible behaviour, or it does not know this device, in which case the
     * push that follows rejects every op `not_authorized` and nothing leaves.
     * Neither case can leak an answer, and both are worth surviving — a
     * self-hosted deployment runs whatever version it runs.
     */
    private suspend fun fetchCrypto(baseUrl: String): ProjectCrypto? {
        val response = http.get("$baseUrl/api/v1/devices/${store.deviceId}/crypto") {
            expectSuccess = false
        }
        if (response.status == HttpStatusCode.NotFound) return null
        if (!response.status.isSuccess()) {
            error("crypto config refused: HTTP ${response.status.value}")
        }
        val body: WireDeviceCryptoResponse = response.body()
        return ProjectCrypto(
            securityMode = body.securityMode,
            projectKeys = body.projectKeys.map {
                ProjectKey(it.keyId, Hex.decode(it.publicKey), it.role, it.label)
            },
        )
    }

    /**
     * A content key is marked uploaded only once an op encrypted under it was
     * accepted. That acceptance is the proof: the server rejects an op naming a
     * key it does not hold with `unknown_content_key`, so an accepted op cannot
     * exist without its key having been stored.
     */
    private fun markUploadedKeys(prepared: PreparedBatch, accepted: Set<String>) {
        if (prepared.keys.isEmpty()) return
        val landed = prepared.ops
            .filter { it.opId in accepted }
            .mapNotNull { it.contentKeyId }
            .toSet()
        prepared.keys.filter { it.contentKeyId in landed }
            .forEach { store.markContentKeyUploaded(it.contentKeyId) }
    }

    private suspend fun pushBatch(baseUrl: String, prepared: PreparedBatch): WirePushResponse =
        http.post("$baseUrl/api/v1/sync/push") {
            contentType(ContentType.Application.Json)
            setBody(WirePushRequest(store.deviceId, prepared.ops, prepared.keys))
        }.body()

    private suspend fun pullPage(
        baseUrl: String,
        cursor: Long,
        wantForms: Boolean = false,
        wantDatasets: Boolean = false,
    ): WirePullResponse =
        http.get("$baseUrl/api/v1/sync/pull") {
            parameter("cursor", cursor)
            parameter("limit", config.pullLimit)
            val scopes = buildList {
                if (wantForms) add("forms")
                if (wantDatasets) add("datasets")
            }
            if (scopes.isNotEmpty()) {
                parameter("scope", scopes.joinToString(","))
                // Deployment is per environment, so the server cannot answer
                // either question without knowing whose device is asking.
                parameter("deviceId", store.deviceId)
            }
        }.body()

    /**
     * Bring the local form store in line with the server's manifest, and report
     * how many documents were fetched.
     *
     * Only the versions this device does not already hold are fetched, compared
     * on the server's content checksum. That is the whole reason the manifest
     * and the documents are separate calls: a device that is up to date spends
     * a few hundred bytes on a sync instead of re-reading every form it has.
     *
     * A document that will not fetch is skipped rather than abandoning the
     * batch. The manifest is still applied for the rest, and a version the
     * device already holds is simply re-marked as deployed — so one unreachable
     * form does not cost the device the others.
     *
     * A **null** manifest means the server said nothing about forms — it
     * predates form delivery, or this pull did not ask — and the device's forms
     * are left exactly as they are. An **empty** manifest is a real answer:
     * this environment deploys nothing, and the device acts on it. Treating a
     * silent server as an empty manifest would undeploy every form on the
     * device and leave an enumerator with no interview to start, caused
     * entirely by a sync that succeeded.
     */
    private suspend fun refreshForms(
        baseUrl: String,
        store: FormStore,
        manifest: List<WireDeployedFormVersion>?,
    ): FormRefresh {
        if (manifest == null) return FormRefresh(0, emptyList())

        val entries = manifest.map {
            FormManifestEntry(
                formVersionId = it.formVersionId,
                formId = it.formId,
                version = it.version,
                title = it.title,
                irChecksum = it.irChecksum,
            )
        }

        val documents = mutableMapOf<String, String>()
        val undelivered = mutableListOf<String>()
        for (entry in store.missingFrom(entries)) {
            val document = try {
                withRetry { fetchFormVersion(baseUrl, entry.formVersionId) }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                // Skipped, so one unreachable form does not cost the device the
                // others — but RECORDED, which it was not. A manifest entry
                // whose document will not fetch and which this device does not
                // already hold simply vanishes: `applyManifest` has nothing to
                // upsert and `markDeployed` updates no row. The sync then
                // reports success, the device holds no form, and nothing
                // anywhere says why — indistinguishable, from the phone, from a
                // project that has deployed nothing. Found while verifying the
                // settings screen, which states that diagnosis out loud and so
                // would have stated it wrongly.
                undelivered += "${entry.formId} v${entry.version}"
                continue
            }
            documents[entry.formVersionId] = document
        }

        store.applyManifest(entries, documents)
        // Retention (Form IR §9): only versions the server has withdrawn AND
        // no submission on this device refers to. Run here rather than inside
        // applyManifest so a truncated manifest cannot delete a form as a side
        // effect of being applied.
        store.prune()
        return FormRefresh(documents.size, undelivered)
    }

    private data class DatasetRefresh(val rows: Int, val incomplete: List<String>)

    /** A dataset row on the wire and in the store: text to text, nothing else. */
    private val RowSerializer = MapSerializer(String.serializer(), String.serializer())

    /**
     * Bring the local reference data in line with the server's manifest.
     *
     * Only versions this device does not already hold **whole** are fetched,
     * compared on the server's checksum. A version whose transfer stopped half
     * way counts as missing and resumes from its cursor rather than starting
     * again: 38,000 rows over a field connection is many requests and at least
     * one of them will fail.
     *
     * A **null** manifest means the server said nothing about datasets, and the
     * device leaves what it holds alone. An **empty** manifest is a real answer
     * — this device's forms reference no lists — and it acts on it by pruning.
     * Collapsing the two would have a device delete a village list because it
     * synced against an older build.
     *
     * A list that does not finish is **reported**, and that is the whole point
     * of the function returning anything. Every other failure in a sync has a
     * symptom: an unsent answer sits in the outbox, a missing form leaves
     * nothing to start. A stale village list has none — the form opens, the
     * list scrolls, the search works, and the answers are wrong. The store
     * refuses to serve an incomplete version so the enumerator sees an empty
     * list rather than a short one, and this sentence is what says why.
     */
    private suspend fun refreshDatasets(
        baseUrl: String,
        store: DatasetStore,
        manifest: List<WireDeployedDatasetVersion>?,
    ): DatasetRefresh {
        if (manifest == null) return DatasetRefresh(0, emptyList())

        val entries = manifest.map {
            DatasetManifestEntry(
                formVersionId = it.formVersionId,
                datasetKey = it.datasetKey,
                datasetVersionId = it.datasetVersionId,
                version = it.version,
                rowCount = it.rowCount,
                checksum = it.checksum,
                filterColumns = it.filterColumns,
            )
        }
        store.applyManifest(entries)

        var fetched = 0
        val incomplete = mutableListOf<String>()
        for (entry in store.missingFrom(entries)) {
            try {
                // A complete earlier version of the same list is a base to diff
                // against, and the difference is the whole of part 5: a device
                // on v3 receiving v4 with 200 changed rows should not spend a
                // morning on 38,000. With no base there is nothing to diff and
                // the paged full transfer is the first-sync path.
                val base = store.deltaBaseFor(entry.datasetKey, entry.datasetVersionId)
                fetched += if (base != null) {
                    fetchDatasetDelta(baseUrl, store, entry, base)
                } else {
                    fetchDatasetRows(baseUrl, store, entry.datasetVersionId)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                // Skipped so one unreachable list does not cost the device the
                // others — and recorded, because the store will now refuse to
                // serve this one and something has to say why.
                incomplete += "${entry.datasetKey} v${entry.version}"
            }
        }

        // Retention (Form IR §9) one level down from FormStore's: whatever form
        // versions survived pruning, their lists survive with them. Run after
        // the fetches so a manifest that arrived truncated cannot delete a list
        // as a side effect of being applied.
        store.prune()
        return DatasetRefresh(fetched, incomplete)
    }

    /**
     * Every remaining page of one dataset version, resuming from its cursor.
     *
     * The version is marked complete only when a page comes back with no
     * `nextCursor`, which is the difference between the whole list and most of
     * one. Until then the store will not serve it at all.
     */
    private suspend fun fetchDatasetRows(
        baseUrl: String,
        store: DatasetStore,
        datasetVersionId: String,
    ): Int {
        var cursor = store.find(datasetVersionId)?.nextCursor
        var rows = 0
        while (true) {
            val page: WireDatasetRowsPage = withRetry {
                http.get("$baseUrl/api/v1/datasets/versions/$datasetVersionId/rows") {
                    if (cursor != null) parameter("cursor", cursor)
                }.body()
            }
            val stored = page.rows.map { row ->
                // The record key is the value column's cell, exactly (§3.1) —
                // and the store keys on it, so a row with none would collide
                // with every other row that has none. The server refuses to
                // publish such a version; this is the second lock on it.
                val key = row["name"] ?: row.values.firstOrNull() ?: ""
                key to SyncJson.encodeToString(RowSerializer, row)
            }
            store.appendRows(datasetVersionId, stored, page.nextCursor)
            rows += stored.size
            cursor = page.nextCursor ?: return rows
        }
    }

    /**
     * The changes between a version this device holds and the one it needs.
     *
     * A **409 is not retried and not fallen back from.** The server refusing a
     * diff means it does not recognise where this device says it is — and
     * quietly fetching the whole list instead would leave the device correct
     * and the disagreement invisible, which is the failure this whole guard
     * exists for. It propagates, and the sync reports it.
     */
    private suspend fun fetchDatasetDelta(
        baseUrl: String,
        store: DatasetStore,
        entry: DatasetManifestEntry,
        base: String,
    ): Int {
        var cursor: String? = null
        var applied = 0
        var first = true
        while (true) {
            val page: WireDatasetDeltaPage = withRetry {
                http.get("$baseUrl/api/v1/datasets/versions/$base/delta") {
                    parameter("formVersionId", entry.formVersionId)
                    parameter("datasetKey", entry.datasetKey)
                    if (cursor != null) parameter("cursor", cursor)
                }.body()
            }
            store.applyDelta(
                datasetVersionId = entry.datasetVersionId,
                fromDatasetVersionId = base,
                changed = page.changed.map { row ->
                    val key = row["name"] ?: row.values.firstOrNull() ?: ""
                    key to SyncJson.encodeToString(RowSerializer, row)
                },
                deleted = page.deleted,
                nextCursor = page.nextCursor,
                // The rows this device already holds are copied across on the
                // first page only; later pages patch what is already there.
                seed = first,
            )
            applied += page.changed.size + page.deleted.size
            first = false
            cursor = page.nextCursor ?: return applied
        }
    }

    /**
     * The IR document behind one manifest entry, as JSON text for the store.
     *
     * Re-serialised rather than relayed byte for byte, so this text is not what
     * the server hashed — see the note on `ir_checksum` in forms.sq. It is the
     * same *document*: key order is the only thing that can differ, and the
     * engine compiles a document, not a byte string.
     */
    private suspend fun fetchFormVersion(baseUrl: String, formVersionId: String): String {
        val body: WireFormVersionDocument =
            http.get("$baseUrl/api/v1/forms/versions/$formVersionId").body()
        return SyncJson.encodeToString(JsonElement.serializer(), body.form)
    }

    /** Exponential backoff; the last failure propagates to syncOnce's catch. */
    private suspend fun <T> withRetry(block: suspend () -> T): T {
        var attempt = 0
        while (true) {
            try {
                return block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: DeviceRegistrationException) {
                // A refusal is a decision, not a hiccup: an unseeded database
                // or a revoked device will still be that way in 30 seconds.
                throw e
            } catch (e: Exception) {
                attempt++
                if (attempt >= config.maxAttempts) throw e
                val backoff = (config.baseDelayMs shl (attempt - 1)).coerceAtMost(config.maxDelayMs)
                delay(backoff)
            }
        }
    }

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
        // Kept as it arrived. This device cannot open it — only a project
        // private key holder can (envelope §7) — but discarding it would lose
        // an op the submission's history depends on.
        valueCiphertext = valueCiphertext,
        contentKeyId = contentKeyId,
        nonce = nonce,
    )
}
