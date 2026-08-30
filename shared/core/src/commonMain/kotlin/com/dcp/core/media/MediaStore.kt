package com.dcp.core.media

import app.cash.sqldelight.coroutines.asFlow
import app.cash.sqldelight.coroutines.mapToList
import com.dcp.core.db.DcpDatabase
import com.dcp.core.sync.WrappedKeyRecord
import kotlin.coroutines.CoroutineContext
import kotlin.time.Clock
import kotlin.time.ExperimentalTime
import kotlin.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * A file staged on this device: encrypted, chunked, content-addressed over its
 * ciphertext, and waiting to be uploaded.
 *
 * [mediaKey] is the per-file key of encryption envelope §6. It lives in the
 * SQLCipher database and nowhere else — that is what makes the chunks on disk
 * encrypted at rest without a second key hierarchy (§14).
 */
data class StagedMedia(
    val mediaId: String,
    val submissionId: String,
    val opId: String?,
    val fieldPath: String,
    val filename: String,
    val mimeType: String,
    /** The file as captured, before encryption. Goes into the op reference. */
    val plaintextSize: Long,
    /** What is on disk and on the wire: plaintext plus a GCM tag per chunk. */
    val ciphertextSize: Long,
    val chunkCount: Int,
    /** Over the CIPHERTEXT, never the plaintext (§6). */
    val ciphertextHash: String,
    val mediaKey: ByteArray,
    val contentKeyId: String,
    val encrypted: Boolean,
    val storageDir: String,
    val createdAt: String,
    val uploadId: String?,
    val uploaded: Boolean,
    val lastError: String?,
) {
    // ByteArray gives identity equality, which would make two equal rows
    // compare unequal.
    override fun equals(other: Any?): Boolean =
        this === other ||
            (other is StagedMedia &&
                mediaId == other.mediaId &&
                submissionId == other.submissionId &&
                opId == other.opId &&
                ciphertextHash == other.ciphertextHash &&
                mediaKey.contentEquals(other.mediaKey) &&
                uploaded == other.uploaded)

    override fun hashCode(): Int =
        ((mediaId.hashCode() * 31 + ciphertextHash.hashCode()) * 31 +
            mediaKey.contentHashCode()) * 31 + uploaded.hashCode()

    /**
     * The value a `set` op carries for this file (Form IR §2.1:
     * `{id, filename, hash, size}`).
     *
     * `size` is the PLAINTEXT size, because that is what a reader means by the
     * size of a photograph; `hash` is the CIPHERTEXT hash, because that is what
     * addresses it on the server and hashing the plaintext would let the server
     * confirm two submissions hold the same image (§6). The two describe
     * different things on purpose.
     */
    fun reference(): MediaReference =
        MediaReference(id = mediaId, filename = filename, hash = ciphertextHash, size = plaintextSize)
}

/** The media reference an operation value carries. */
data class MediaReference(
    val id: String,
    val filename: String,
    val hash: String,
    val size: Long,
) {
    fun toFormValue(): com.dcp.form.FormValue.MediaRef =
        com.dcp.form.FormValue.MediaRef(id = id, filename = filename, hash = hash, size = size)
}

/** The project's capture settings (server: project.media_*). */
data class MediaPolicy(
    val imageMaxDimension: Int = DEFAULT_IMAGE_MAX_DIMENSION,
    val imageQuality: Int = DEFAULT_IMAGE_QUALITY,
    val gpsMaxAccuracyM: Int = DEFAULT_GPS_MAX_ACCURACY_M,
) {
    companion object {
        /**
         * Matching the server's column defaults. Used before the first sync —
         * a device that has never reached the server still has to be able to
         * capture, and these are the settings it captures under.
         */
        const val DEFAULT_IMAGE_MAX_DIMENSION = 1600
        const val DEFAULT_IMAGE_QUALITY = 80
        const val DEFAULT_GPS_MAX_ACCURACY_M = 50
    }
}

/**
 * Local media staging and upload state.
 *
 * A sibling of [com.dcp.core.sync.SubmissionStore] over the same database:
 * media and the op that references it are written in one transaction, so a
 * device cannot die between the two and leave an op pointing at a file that was
 * never staged.
 */
@OptIn(ExperimentalTime::class)
class MediaStore(
    db: DcpDatabase,
    private val now: () -> Instant = { Clock.System.now() },
) {
    private val queries = db.mediaQueries

    private fun toStaged(row: com.dcp.core.db.Media) = StagedMedia(
        mediaId = row.media_id,
        submissionId = row.submission_id,
        opId = row.op_id,
        fieldPath = row.field_path,
        filename = row.filename,
        mimeType = row.mime_type,
        plaintextSize = row.plaintext_size,
        ciphertextSize = row.ciphertext_size,
        chunkCount = row.chunk_count.toInt(),
        ciphertextHash = row.ciphertext_hash,
        mediaKey = row.media_key,
        contentKeyId = row.content_key_id,
        encrypted = row.encrypted == 1L,
        storageDir = row.storage_dir,
        createdAt = row.created_at,
        uploadId = row.upload_id,
        uploaded = row.uploaded == 1L,
        lastError = row.last_error,
    )

    /**
     * Records a staged file and the wraps of its media key, in one transaction.
     *
     * Together because a media key without its wraps is a file nobody can ever
     * open — including us, once the key material is gone with the device.
     */
    fun put(media: StagedMedia, wraps: List<WrappedKeyRecord>): StagedMedia =
        queries.transactionWithResult {
            queries.insertMedia(
                media.mediaId,
                media.submissionId,
                media.opId,
                media.fieldPath,
                media.filename,
                media.mimeType,
                media.plaintextSize,
                media.ciphertextSize,
                media.chunkCount.toLong(),
                media.ciphertextHash,
                media.mediaKey,
                media.contentKeyId,
                if (media.encrypted) 1L else 0L,
                media.storageDir,
                media.createdAt,
            )
            for (wrap in wraps) {
                queries.insertMediaWrap(
                    media.mediaId, wrap.projectKeyId, wrap.ephemeralPublic,
                    wrap.nonce, wrap.wrappedKey,
                )
            }
            media
        }

    fun get(mediaId: String): StagedMedia? =
        queries.getMedia(mediaId).executeAsOneOrNull()?.let(::toStaged)

    fun forSubmission(submissionId: String): List<StagedMedia> =
        queries.mediaForSubmission(submissionId).executeAsList().map(::toStaged)

    /** Oldest first: photographs upload in the order they were taken. */
    fun pending(limit: Int): List<StagedMedia> =
        queries.pendingMedia(limit.toLong()).executeAsList().map(::toStaged)

    fun pendingCount(): Long = queries.countPendingMedia().executeAsOne()

    fun observePendingCount(
        context: CoroutineContext = Dispatchers.Default,
    ): Flow<Long> =
        queries.countPendingMedia().asFlow().mapToList(context).map { it.firstOrNull() ?: 0L }

    fun observeForSubmission(
        submissionId: String,
        context: CoroutineContext = Dispatchers.Default,
    ): Flow<List<StagedMedia>> =
        queries.mediaForSubmission(submissionId).asFlow().mapToList(context)
            .map { rows -> rows.map(::toStaged) }

    fun setOpId(mediaId: String, opId: String) = queries.setMediaOpId(opId, mediaId)

    fun setUploadId(mediaId: String, uploadId: String?) = queries.setUploadId(uploadId, mediaId)

    /**
     * Records that this file's upload must carry ciphertext after all, and
     * stores the wraps that make it openable.
     *
     * One transaction: a file marked encrypted with no wraps is a file nobody
     * can ever open, and it would look exactly like a correctly protected one.
     */
    fun markEncrypted(mediaId: String, contentKeyId: String, wraps: List<WrappedKeyRecord>) =
        queries.transaction {
            queries.clearMediaWraps(mediaId)
            for (wrap in wraps) {
                queries.insertMediaWrap(
                    mediaId, wrap.projectKeyId, wrap.ephemeralPublic, wrap.nonce, wrap.wrappedKey,
                )
            }
            queries.markMediaEncrypted(contentKeyId, mediaId)
        }

    fun wrapsFor(mediaId: String): List<WrappedKeyRecord> =
        queries.wrapsForMedia(mediaId).executeAsList().map {
            WrappedKeyRecord(it.project_key_id, it.ephemeral_public, it.nonce, it.wrapped_key)
        }

    /**
     * Which chunks the server has acknowledged, ascending.
     *
     * Rows rather than a high-water mark: a chunk that failed mid-upload leaves
     * a gap, and resuming from the first gap would re-send everything after it.
     */
    fun uploadedChunks(mediaId: String): Set<Int> =
        queries.uploadedChunks(mediaId).executeAsList().map { it.toInt() }.toSet()

    fun markChunkUploaded(mediaId: String, chunkIndex: Int) =
        queries.markChunkUploaded(mediaId, chunkIndex.toLong())

    /**
     * Replaces this device's idea of what the server holds.
     *
     * The server's answer wins, always. It is the one that decides whether a
     * chunk has to be sent again, and a device that trusted its own record over
     * the server's would skip a chunk the server never received and then fail
     * `complete` with no way to recover but starting over.
     */
    fun replaceChunkState(mediaId: String, uploaded: Collection<Int>) = queries.transaction {
        queries.clearChunkState(mediaId)
        uploaded.forEach { queries.markChunkUploaded(mediaId, it.toLong()) }
    }

    fun markUploaded(mediaId: String) = queries.markMediaUploaded(mediaId)

    fun recordError(mediaId: String, message: String) =
        queries.recordMediaError(message, mediaId)

    /** Forgets a staged file entirely. The caller deletes its bytes. */
    fun forget(mediaId: String) = queries.transaction {
        queries.clearChunkState(mediaId)
        queries.clearMediaWraps(mediaId)
        queries.deleteMedia(mediaId)
    }

    /**
     * The cached capture policy, or the server's own defaults before the first
     * sync. Never null: a device that has never reached a server still has to
     * be able to capture, and refusing to would make first-run unusable in
     * exactly the places this product exists for.
     */
    fun policy(): MediaPolicy =
        queries.getMediaPolicy().executeAsOneOrNull()?.let {
            MediaPolicy(
                imageMaxDimension = it.image_max_dimension.toInt(),
                imageQuality = it.image_quality.toInt(),
                gpsMaxAccuracyM = it.gps_max_accuracy_m.toInt(),
            )
        } ?: MediaPolicy()

    fun putPolicy(policy: MediaPolicy) = queries.putMediaPolicy(
        policy.imageMaxDimension.toLong(),
        policy.imageQuality.toLong(),
        policy.gpsMaxAccuracyM.toLong(),
        now().toString(),
    )
}
