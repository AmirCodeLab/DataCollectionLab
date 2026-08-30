package com.dcp.core.media

import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.allocArrayOf
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.usePinned
import platform.Foundation.NSData
import platform.Foundation.NSDocumentDirectory
import platform.Foundation.NSFileManager
import platform.Foundation.NSSearchPathForDirectoriesInDomains
import platform.Foundation.NSURL
import platform.Foundation.NSUserDomainMask
import platform.Foundation.create
import platform.Foundation.dataWithContentsOfFile
import platform.Foundation.writeToFile
import platform.posix.memcpy

/**
 * iOS: chunks under the app's Documents directory, in `media/<mediaId>/`.
 *
 * The bytes are ciphertext (see the expect declaration), which is what makes
 * this safe in a directory iTunes/Finder backup can reach. iOS Data Protection
 * would add a second layer, but relying on it alone would make the guarantee
 * depend on the device having a passcode set — and a device without one is
 * exactly the device this protects.
 */
@OptIn(ExperimentalForeignApi::class)
actual class MediaFileStore {

    private val root: String = run {
        val documents = NSSearchPathForDirectoriesInDomains(
            NSDocumentDirectory, NSUserDomainMask, true,
        ).first() as String
        "$documents/media"
    }

    private fun dir(mediaId: String): String {
        require(
            mediaId.isNotEmpty() &&
                mediaId.all { it.isLetterOrDigit() || it == '-' || it == '_' },
        ) { "media id is used as a directory name and must be a plain identifier: $mediaId" }
        return "$root/$mediaId"
    }

    private fun chunkPath(mediaId: String, chunkIndex: Int): String =
        "${dir(mediaId)}/${chunkIndex.toString().padStart(8, '0')}"

    actual fun write(mediaId: String, chunkIndex: Int, data: ByteArray) {
        NSFileManager.defaultManager.createDirectoryAtPath(
            dir(mediaId), withIntermediateDirectories = true, attributes = null, error = null,
        )
        val target = chunkPath(mediaId, chunkIndex)
        // Atomically: NSData writes to a temporary and renames, so a chunk is
        // either fully there or not there at all.
        val nsData = memScoped {
            NSData.create(bytes = allocArrayOf(data), length = data.size.toULong())
        }
        nsData.writeToFile(target, atomically = true)
        // Keep it out of iCloud backups: this is a local staging copy of data
        // that is also going to the server, and backing it up would put project
        // media on a third party's disk without anyone choosing that.
        NSURL.fileURLWithPath(target).setResourceValue(true, NSURLIsExcludedFromBackupKey, null)
    }

    actual fun read(mediaId: String, chunkIndex: Int): ByteArray {
        val path = chunkPath(mediaId, chunkIndex)
        val data = NSData.dataWithContentsOfFile(path)
            ?: throw MediaFileMissing("no chunk $chunkIndex of $mediaId at $path")
        val length = data.length.toInt()
        val bytes = ByteArray(length)
        if (length > 0) {
            bytes.usePinned { memcpy(it.addressOf(0), data.bytes, data.length) }
        }
        return bytes
    }

    actual fun exists(mediaId: String, chunkIndex: Int): Boolean =
        NSFileManager.defaultManager.fileExistsAtPath(chunkPath(mediaId, chunkIndex))

    actual fun directoryFor(mediaId: String): String = dir(mediaId)

    actual fun delete(mediaId: String) {
        NSFileManager.defaultManager.removeItemAtPath(dir(mediaId), error = null)
    }
}

private const val NSURLIsExcludedFromBackupKey = "NSURLIsExcludedFromBackupKey"
