package com.dcp.core.media

import com.dcp.core.crypto.EncryptionEnvelope
import com.dcp.core.crypto.Hex
import com.dcp.core.sync.SecurityMode
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.WrappedKeyRecord
import com.dcp.core.sync.SyncJson
import com.dcp.core.sync.WireWrappedKey
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json
import io.ktor.client.plugins.expectSuccess
import io.ktor.client.request.get
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import kotlin.coroutines.cancellation.CancellationException

/** The client this uses when the caller does not supply one. */
fun defaultMediaHttpClient(): HttpClient = HttpClient(CIO) {
    expectSuccess = true
    install(ContentNegotiation) { json(SyncJson) }
}

/** What one pass of the upload loop achieved. */
data class MediaUploadResult(
    val filesCompleted: Int,
    val chunksSent: Int,
    val chunksSkipped: Int,
    val filesFailed: Int,
    val error: String? = null,
) {
    val isSuccess: Boolean get() = error == null && filesFailed == 0
}

/**
 * Uploads staged media, resumably (sync protocol §9, encryption envelope §6).
 *
 * Runs after the op push rather than before it, and that ordering is
 * deliberate: an operation naming a file the server has never heard of is
 * accepted and marked pending, so ops-first costs nothing and gets the answers
 * — the small, cheap, irreplaceable part — off the device first. A 3 MB
 * photograph that takes four attempts over a week must never be what holds up a
 * questionnaire.
 *
 * **Resumption is the server's answer, not ours.** Opening a session returns
 * the chunk indexes it already holds, and those are the ones skipped. A device
 * that trusted its own record instead would skip a chunk the server never
 * received, and then fail `complete` with no way forward but starting over.
 *
 * **Nothing is re-encrypted here.** The chunks were encrypted once, at capture,
 * and are uploaded byte for byte — so a resumed upload provably sends the same
 * bytes as the first attempt, and the content hash computed at capture is the
 * one the server verifies. The exception is `standard` mode, where the server
 * is entitled to read the file: the chunk is decrypted on the way out, and the
 * hash sent is over what was actually uploaded.
 */
class MediaUploader(
    private val store: MediaStore,
    private val files: MediaFileStore,
    private val staging: MediaStaging,
    private val submissions: SubmissionStore,
    /**
     * Where the server is, asked for rather than held — the same reason as
     * [com.dcp.core.sync.SyncClient.serverUrl]: the address is configurable on
     * the device now, and a held copy would need an app restart to follow it.
     *
     * Media rides after the ops in one sync pass, so in production this reads
     * the same value the sync client already snapshotted.
     */
    private val serverUrl: () -> String,
    /**
     * Shared with [com.dcp.core.sync.SyncClient] in production so both use one
     * connection pool. Injected in tests so the mock engine can watch exactly
     * which chunks go out.
     */
    private val http: HttpClient = defaultMediaHttpClient(),
    /** How many files one pass will attempt. Bounded so a sync ends. */
    private val batchSize: Int = 8,
    /**
     * Whether a sealed file's bytes are deleted from the device.
     *
     * On by default: the server has it, it is content-addressed, and a phone
     * with 8 GB of storage collecting photographs fills up in a week otherwise.
     * Off for a deployment that reviews media locally before handing devices
     * back.
     */
    private val deleteAfterUpload: Boolean = true,
    private val envelope: EncryptionEnvelope = EncryptionEnvelope(),
) {

    /**
     * Uploads what is staged. Failures are recorded per file, never thrown:
     * one file the server refuses must not stop the other seven, and field
     * devices sync opportunistically.
     */
    suspend fun uploadPending(): MediaUploadResult {
        var completed = 0
        var sent = 0
        var skipped = 0
        var failed = 0

        val batch = store.pending(batchSize)
        for (media in batch) {
            try {
                val outcome = upload(media)
                sent += outcome.first
                skipped += outcome.second
                completed++
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                failed++
                store.recordError(media.mediaId, e.message ?: "media upload failed")
            }
        }
        return MediaUploadResult(completed, sent, skipped, failed)
    }

    /** How many files are still staged and unsealed. */
    fun pendingCount(): Long = store.pendingCount()

    /**
     * Decides — at UPLOAD time, not capture time — whether the server gets
     * ciphertext, and wraps the media key if it must.
     *
     * This exists because of a real leak found on a device. `MediaStaging`
     * reads the project's security mode from a LOCAL CACHE, and a device that
     * has not yet synced has no cache: a photograph captured before the first
     * sync was staged as "plaintext upload" and later uploaded in the clear to
     * a project_e2e server. The operations in the same submission were
     * encrypted, because the push path refreshes the crypto config first and
     * fails closed — media had no equivalent. The result was a submission whose
     * answers were protected and whose photograph of an identity document was
     * not, on a project whose whole promise is that the server reads nothing.
     *
     * So the mode is resolved here, against the config `SyncClient` has just
     * refreshed, and an unknown mode refuses to upload rather than guessing.
     * A file left staged is recoverable; a plaintext photograph on someone
     * else's server is not.
     */
    private suspend fun resolveEncryption(media: StagedMedia): StagedMedia {
        if (media.encrypted) return media

        val crypto = submissions.projectCrypto()
            ?: error(
                "refusing to upload ${media.mediaId}: this device has never fetched " +
                    "its project's security mode, so it cannot tell whether the server " +
                    "is allowed to read this file. It stays on the device.",
            )
        if (crypto.securityMode == SecurityMode.STANDARD) return media

        if (crypto.projectKeys.isEmpty()) {
            error(
                "refusing to upload ${media.mediaId}: project is in " +
                    "${crypto.securityMode} mode with no active project keys, so the " +
                    "media key could be wrapped to nobody.",
            )
        }

        val wraps = envelope.wrapToRecipients(
            media.mediaKey,
            media.contentKeyId,
            crypto.projectKeys.associate { it.keyId to it.publicKey },
        ).map { WrappedKeyRecord(it.projectKeyId, it.ephemeralPublic, it.nonce, it.wrappedKey) }

        store.markEncrypted(media.mediaId, media.contentKeyId, wraps)
        return media.copy(encrypted = true)
    }

    /** Uploads one file. Returns (chunks sent, chunks skipped). */
    private suspend fun upload(staged: StagedMedia): Pair<Int, Int> {
        val media = resolveEncryption(staged)
        val session = openSession(media)
        store.setUploadId(media.mediaId, session.uploadId)

        // The server's list is authoritative. Ours is a cache of it, and a
        // stale cache here means a chunk that is never sent.
        store.replaceChunkState(media.mediaId, session.receivedChunks)
        val alreadyThere = session.receivedChunks.toSet()

        if (session.status == "complete") {
            // Nothing to do — the completion response was lost last time, not
            // the upload. Recording it now stops the device retrying forever.
            finish(media)
            return 0 to media.chunkCount
        }

        var sent = 0
        val chunkBase = "${serverUrl()}/api/v1/media/upload-sessions/${session.uploadId}/chunks"
        for (index in 0 until media.chunkCount) {
            if (index in alreadyThere) continue
            val body = chunkBytes(media, index)
            http.put("$chunkBase/$index") {
                contentType(ContentType.Application.OctetStream)
                setBody(body)
            }
            store.markChunkUploaded(media.mediaId, index)
            sent++
        }

        val completed: WireMediaCompleteResponse = http.post(
            "${serverUrl()}/api/v1/media/upload-sessions/${session.uploadId}/complete",
        ) {
            contentType(ContentType.Application.Json)
            setBody(WireMediaCompleteRequest(uploadHash(media)))
        }.body()

        if (completed.hash != uploadHash(media)) {
            // The server recomputes rather than echoing, so a disagreement here
            // means the bytes it holds are not the bytes we staged. Refusing to
            // mark it uploaded keeps it in the queue for another attempt.
            error(
                "server sealed ${media.mediaId} as ${completed.hash}, we staged " +
                    uploadHash(media),
            )
        }
        finish(media)
        return sent to alreadyThere.size
    }

    private fun finish(media: StagedMedia) {
        store.markUploaded(media.mediaId)
        if (deleteAfterUpload) files.delete(media.mediaId)
    }

    /**
     * The bytes for one chunk, as they go on the wire.
     *
     * Encrypted projects send the staged ciphertext untouched. `standard` mode
     * decrypts on the way out, because there the server is entitled to read the
     * file and ciphertext it has no key for would be useless to it — the file
     * on THIS device stays encrypted either way.
     */
    private suspend fun chunkBytes(media: StagedMedia, index: Int): ByteArray =
        if (media.encrypted) files.read(media.mediaId, index)
        else staging.readChunk(media, index)

    /**
     * The hash the server will verify: over what was actually uploaded.
     *
     * For an encrypted file that is the ciphertext hash computed at capture —
     * never a hash of the plaintext, which would let the server confirm two
     * submissions contain the same photograph (envelope §6). For `standard`
     * mode the uploaded bytes are the plaintext, so the hash is over those, and
     * the mode makes no privacy claim that this would break.
     */
    private suspend fun uploadHash(media: StagedMedia): String =
        if (media.encrypted) media.ciphertextHash else plaintextHash(media)

    private val plaintextHashes = mutableMapOf<String, String>()

    private suspend fun plaintextHash(media: StagedMedia): String =
        plaintextHashes.getOrPut(media.mediaId) {
            com.dcp.core.crypto.EncryptionEnvelope().ciphertextHash(
                (0 until media.chunkCount).map { staging.readChunk(media, it) },
            )
        }

    private suspend fun openSession(media: StagedMedia): WireMediaSessionResponse {
        val response = http.post("${serverUrl()}/api/v1/media/upload-sessions") {
            // The refusal body is the point of this call's error path, and
            // expectSuccess would throw before it could be read.
            expectSuccess = false
            contentType(ContentType.Application.Json)
            setBody(
                WireMediaSessionRequest(
                    mediaId = media.mediaId,
                    submissionId = media.submissionId,
                    deviceId = submissions.deviceId,
                    opId = media.opId,
                    fieldPath = media.fieldPath,
                    mimeType = media.mimeType,
                    sizeBytes = if (media.encrypted) media.ciphertextSize
                    else media.plaintextSize,
                    chunkCount = media.chunkCount,
                    encrypted = media.encrypted,
                    contentKeyId = if (media.encrypted) media.contentKeyId else null,
                    wraps = if (media.encrypted) {
                        store.wrapsFor(media.mediaId).map {
                            WireWrappedKey(
                                projectKeyId = it.projectKeyId,
                                ephemeralPublic = Hex.encode(it.ephemeralPublic),
                                nonce = Hex.encode(it.nonce),
                                wrappedKey = Hex.encode(it.wrappedKey),
                            )
                        }
                    } else {
                        emptyList()
                    },
                )
            )
        }
        if (response.status.isSuccess()) return response.body()

        val raw = runCatching { response.bodyAsText() }.getOrDefault("")
        val detail = runCatching { SyncJson.decodeFromString<WireMediaErrorBody>(raw).detail }
            .getOrNull()
        if (response.status == HttpStatusCode.Gone) {
            // The session expired. The chunks the server holds are still there
            // and a fresh session will name them, so this is recoverable on the
            // next pass rather than a reason to discard the file.
            store.setUploadId(media.mediaId, null)
        }
        error(
            "media upload refused: ${detail?.reason ?: "HTTP ${response.status.value}"} — " +
                (detail?.message ?: raw.ifBlank { response.status.description }),
        )
    }

    /**
     * Refreshes the project's capture policy (compression, GPS threshold).
     *
     * A failure falls back to the cached policy, for the same reason the crypto
     * config does: offline-first is a constraint, and a device two weeks from a
     * tower still has to capture to the project's settings. A device that has
     * never fetched one uses the server's own defaults rather than refusing to
     * capture — unlike encryption, a photograph taken at the wrong resolution
     * is a degraded answer, not a disclosed one.
     */
    suspend fun refreshPolicy(): MediaPolicy {
        val response = try {
            http.get("${serverUrl()}/api/v1/devices/${submissions.deviceId}/media-policy") {
                expectSuccess = false
            }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            return store.policy()
        }
        if (!response.status.isSuccess()) return store.policy()

        val body: WireMediaPolicyResponse = response.body()
        val policy = MediaPolicy(
            imageMaxDimension = body.policy.imageMaxDimension,
            imageQuality = body.policy.imageQuality,
            gpsMaxAccuracyM = body.policy.gpsMaxAccuracyM,
        )
        store.putPolicy(policy)
        return policy
    }
}
