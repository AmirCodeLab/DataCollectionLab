package com.dcp.core.media

import android.content.Context
import java.io.File

/**
 * Android: chunks in app-private internal storage (`filesDir/media`), never on
 * external storage.
 *
 * External storage is world-readable to anything holding the legacy
 * permissions, and the whole point of §14 is that a phone picked up off a desk
 * gives up nothing. Internal storage is the app sandbox; the ciphertext is the
 * protection that survives root.
 */
actual class MediaFileStore(context: Context) {

    private val root = File(context.filesDir, "media")

    private fun dir(mediaId: String): File {
        require(mediaId.isNotEmpty() && mediaId.all { it.isLetterOrDigit() || it == '-' || it == '_' }) {
            "media id is used as a directory name and must be a plain identifier: $mediaId"
        }
        return File(root, mediaId)
    }

    private fun chunk(mediaId: String, chunkIndex: Int) =
        File(dir(mediaId), chunkIndex.toString().padStart(8, '0'))

    actual fun write(mediaId: String, chunkIndex: Int, data: ByteArray) {
        val target = chunk(mediaId, chunkIndex)
        target.parentFile?.mkdirs()
        val partial = File(target.parentFile, target.name + ".partial")
        partial.writeBytes(data)
        if (!partial.renameTo(target)) {
            partial.copyTo(target, overwrite = true)
            partial.delete()
        }
    }

    actual fun read(mediaId: String, chunkIndex: Int): ByteArray {
        val file = chunk(mediaId, chunkIndex)
        if (!file.isFile) throw MediaFileMissing("no chunk $chunkIndex of $mediaId at $file")
        return file.readBytes()
    }

    actual fun exists(mediaId: String, chunkIndex: Int): Boolean =
        chunk(mediaId, chunkIndex).isFile

    actual fun directoryFor(mediaId: String): String = dir(mediaId).absolutePath

    actual fun delete(mediaId: String) {
        dir(mediaId).deleteRecursively()
    }
}
