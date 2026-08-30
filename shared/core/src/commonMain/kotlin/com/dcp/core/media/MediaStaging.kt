package com.dcp.core.media

import com.dcp.core.crypto.CONTENT_KEY_BYTES
import com.dcp.core.crypto.EncryptionEnvelope
import com.dcp.core.crypto.EnvelopeException
import com.dcp.core.crypto.MEDIA_CHUNK_BYTES
import com.dcp.core.sync.EncryptionUnavailableException
import com.dcp.core.sync.ProjectCrypto
import com.dcp.core.sync.SecurityMode
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.Ulid
import com.dcp.core.sync.WrappedKeyRecord
import dev.whyoleg.cryptography.random.CryptographyRandom
import kotlin.time.Clock
import kotlin.time.ExperimentalTime

/**
 * Turns captured bytes into a staged, encrypted, chunked file ready to upload
 * (encryption envelope §6).
 *
 * The order of operations is the security property, so it is worth stating
 * plainly:
 *
 *     camera buffer -> compress in memory -> encrypt in memory -> write chunks
 *
 * The plaintext never reaches the disk. Not to a cache file, not to a
 * MediaStore entry, not to a temporary the compressor wanted — a photograph of
 * an ID card sitting in cleartext for the two seconds between capture and
 * encryption is exactly the exposure §14 spent a release closing for the
 * database, and it would be a strange thing to reopen for the photograph.
 *
 * Consequences of doing it this way, all of them wanted:
 *
 * * **The staged file IS the upload.** Chunks are encrypted once, here, and
 *   uploaded byte for byte. Nothing is re-encrypted on the way out, so a
 *   resumed upload provably sends the same bytes as the first attempt.
 * * **The content hash is computed once.** Over the ciphertext (§6), at
 *   capture, and it is the same hash the server verifies at `complete`.
 * * **The media key is per file** (§6), so a file can later be handed to a
 *   third party without disclosing the rest of the submission, and a corrupted
 *   upload affects one file.
 *
 * Encryption here is unconditional, including in `standard` mode. At-rest
 * protection on the device is not the project's server-side trust model: a
 * `standard` project trusts its own server, which says nothing about the phone
 * left on a clinic desk. What the mode decides is whether the *upload* carries
 * ciphertext — see [MediaUploader].
 */
@OptIn(ExperimentalTime::class)
class MediaStaging(
    private val store: MediaStore,
    private val files: MediaFileStore,
    private val submissions: SubmissionStore,
    private val envelope: EncryptionEnvelope = EncryptionEnvelope(),
    private val random: (Int) -> ByteArray = { CryptographyRandom.nextBytes(it) },
    private val now: () -> kotlin.time.Instant = { Clock.System.now() },
) {

    /**
     * Stages one captured file and returns it.
     *
     * [plaintext] is consumed and never written anywhere. The caller should
     * hold no other reference to it once this returns; on a platform with a
     * compacting collector we cannot promise the buffer is scrubbed, which is
     * stated in §14.8's terms — a running, unlocked device is out of scope.
     *
     * @param submissionId the draft this file belongs to
     * @param fieldPath the form field it answers
     * @param crypto the project's recipient set; null before the first sync
     */
    suspend fun stage(
        submissionId: String,
        fieldPath: String,
        filename: String,
        mimeType: String,
        plaintext: ByteArray,
        crypto: ProjectCrypto?,
    ): StagedMedia {
        if (plaintext.isEmpty()) {
            throw IllegalArgumentException("refusing to stage an empty file for $fieldPath")
        }

        val instant = now()
        val mediaId = Ulid.generate(instant.toEpochMilliseconds())
        val contentKeyId = Ulid.generate(instant.toEpochMilliseconds())
        val mediaKey = random(CONTENT_KEY_BYTES)

        // Whether the SERVER gets ciphertext. On the device it is encrypted
        // either way — see the class comment.
        val mode = crypto?.securityMode ?: SecurityMode.STANDARD
        val uploadEncrypted = mode != SecurityMode.STANDARD

        val wraps: List<WrappedKeyRecord> = if (uploadEncrypted) {
            if (crypto == null || crypto.projectKeys.isEmpty()) {
                // Wrapping to nobody produces a file nobody — including the
                // people who collected it — can ever open again.
                throw EncryptionUnavailableException(
                    "project is in $mode mode but has no active project keys to wrap " +
                        "the media key for $fieldPath to",
                )
            }
            try {
                envelope.wrapToRecipients(
                    mediaKey, contentKeyId, crypto.projectKeys.associate { it.keyId to it.publicKey },
                ).map { WrappedKeyRecord(it.projectKeyId, it.ephemeralPublic, it.nonce, it.wrappedKey) }
            } catch (cause: EnvelopeException) {
                throw EncryptionUnavailableException(
                    "could not wrap the media key for $mediaId: ${cause.message}",
                )
            }
        } else {
            emptyList()
        }

        // Chunk, encrypt, write. One chunk at a time, so a 20 MB file needs
        // 4 MiB of working memory rather than 40 MB of it — the phones this
        // runs on will kill the process for the latter.
        val ciphertextChunks = mutableListOf<ByteArray>()
        var chunkIndex = 0
        var offset = 0
        while (offset < plaintext.size) {
            val end = minOf(offset + MEDIA_CHUNK_BYTES, plaintext.size)
            val encrypted = envelope.encryptMediaChunk(
                chunk = plaintext.copyOfRange(offset, end),
                mediaKey = mediaKey,
                mediaId = mediaId,
                chunkIndex = chunkIndex.toLong(),
            ).ciphertext
            files.write(mediaId, chunkIndex, encrypted)
            ciphertextChunks.add(encrypted)
            offset = end
            chunkIndex++
        }

        val staged = StagedMedia(
            mediaId = mediaId,
            submissionId = submissionId,
            // Filled in by the caller once the op exists — see [attachOp].
            opId = null,
            fieldPath = fieldPath,
            filename = filename,
            mimeType = mimeType,
            plaintextSize = plaintext.size.toLong(),
            ciphertextSize = ciphertextChunks.sumOf { it.size }.toLong(),
            chunkCount = chunkIndex,
            ciphertextHash = envelope.ciphertextHash(ciphertextChunks),
            mediaKey = mediaKey,
            contentKeyId = contentKeyId,
            encrypted = uploadEncrypted,
            storageDir = files.directoryFor(mediaId),
            createdAt = instant.toString(),
            uploadId = null,
            uploaded = false,
            lastError = null,
        )
        return store.put(staged, wraps)
    }

    /**
     * Stages a file and writes the `set` op that references it, in one step.
     *
     * Two writes rather than one transaction is the honest description — the
     * chunks are on the filesystem and cannot join a database transaction —
     * so the order is chosen for which half is survivable alone: the file is
     * staged first, and if the process dies before the op is written the
     * result is an orphaned staged file, which [MediaStaging.forget] can clean
     * up. The other order would leave an op referencing a file that does not
     * exist, and that one is not recoverable on the device.
     */
    suspend fun captureInto(
        submissionId: String,
        formId: String,
        formVersion: Int,
        fieldPath: String,
        filename: String,
        mimeType: String,
        plaintext: ByteArray,
        crypto: ProjectCrypto?,
    ): StagedMedia {
        val staged = stage(submissionId, fieldPath, filename, mimeType, plaintext, crypto)
        val op = submissions.appendOp(
            submissionId = submissionId,
            formId = formId,
            formVersion = formVersion,
            kind = com.dcp.core.sync.OpKind.SET,
            path = fieldPath,
            value = staged.reference().toFormValue(),
        )
        store.setOpId(staged.mediaId, op.opId)
        return staged.copy(opId = op.opId)
    }

    /** Drops a staged file and its bytes. For a capture the user discarded. */
    fun forget(mediaId: String) {
        store.forget(mediaId)
        files.delete(mediaId)
    }

    /**
     * Reads one staged chunk back as plaintext.
     *
     * The only path from disk to plaintext, and it exists for two callers: the
     * thumbnail the enumerator sees after taking a photograph, and the
     * `standard`-mode upload, which sends the file the server is entitled to
     * read.
     */
    suspend fun readChunk(media: StagedMedia, chunkIndex: Int): ByteArray =
        envelope.decryptMediaChunk(
            ciphertext = files.read(media.mediaId, chunkIndex),
            mediaKey = media.mediaKey,
            mediaId = media.mediaId,
            chunkIndex = chunkIndex.toLong(),
        )

    /** The whole file, decrypted. Only for files small enough to hold. */
    suspend fun readAll(media: StagedMedia): ByteArray {
        val parts = (0 until media.chunkCount).map { readChunk(media, it) }
        val out = ByteArray(parts.sumOf { it.size })
        var offset = 0
        for (part in parts) {
            part.copyInto(out, offset)
            offset += part.size
        }
        return out
    }
}
