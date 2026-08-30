package com.dcp.core.media

import java.io.File

/**
 * Desktop: chunks under a root directory the caller chooses, one file per
 * chunk.
 *
 * The bytes here are ciphertext (see the expect declaration) — the desktop OS
 * offers no per-app filesystem sandbox worth relying on, so the file being
 * unreadable without the media key is the whole protection, exactly as on
 * mobile.
 */
actual class MediaFileStore(private val root: File) {

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
        // Write-then-rename: a chunk is either fully there or not there at all.
        // A partially written chunk would hash differently and be blamed on the
        // network at upload time.
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
