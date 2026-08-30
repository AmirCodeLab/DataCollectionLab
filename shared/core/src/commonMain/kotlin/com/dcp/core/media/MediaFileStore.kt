package com.dcp.core.media

/**
 * Where a staged media file's ciphertext chunks live on this device.
 *
 * One directory per media id, one file per chunk. Chunks rather than one file
 * because that is what the upload sends and what resumption resends: a chunk
 * that exists is a chunk that is complete, and there is no half-written object
 * to tell apart from a finished one.
 *
 * **Every byte written through here is already ciphertext.** Encryption
 * happens in [MediaStaging] before the store is ever called, with a per-file
 * media key held in the SQLCipher database (encryption envelope §6, §14). The
 * store has no key and cannot decrypt anything — it is somewhere to put bytes,
 * not somewhere that understands them. That ordering is the whole at-rest
 * guarantee: a photograph of an ID card never exists in the clear on disk, not
 * even for the moment between capture and encryption.
 *
 * Each platform's actual takes its own constructor arguments — Android needs a
 * Context to find the app-private directory, desktop takes a root path —
 * following [com.dcp.core.sync.DatabaseDriverFactory] and
 * [com.dcp.core.security.DatabaseKeyStore].
 */
expect class MediaFileStore {

    /** Writes one chunk, replacing any chunk already at that index. */
    fun write(mediaId: String, chunkIndex: Int, data: ByteArray)

    /** Reads one chunk back. Throws if it is not there. */
    fun read(mediaId: String, chunkIndex: Int): ByteArray

    fun exists(mediaId: String, chunkIndex: Int): Boolean

    /** An opaque platform path, recorded in the database for diagnostics. */
    fun directoryFor(mediaId: String): String

    /**
     * Removes every chunk of one file. Called when the server has sealed the
     * upload and the device no longer needs its copy, and when a capture is
     * abandoned before it is referenced by an op.
     */
    fun delete(mediaId: String)
}

/** Raised when a staged file's bytes are gone from under us. */
class MediaFileMissing(message: String) : Exception(message)
