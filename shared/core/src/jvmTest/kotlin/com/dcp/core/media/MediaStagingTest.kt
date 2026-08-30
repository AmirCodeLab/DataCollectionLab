package com.dcp.core.media

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.crypto.MEDIA_CHUNK_BYTES
import com.dcp.core.db.DcpDatabase
import com.dcp.core.sync.EncryptionUnavailableException
import com.dcp.core.sync.ProjectCrypto
import com.dcp.core.sync.ProjectKey
import com.dcp.core.sync.SecurityMode
import com.dcp.core.sync.SubmissionStore
import com.dcp.form.FormValue
import java.io.File
import java.util.Properties
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking

/**
 * Staging: what happens to a photograph between the camera and the disk.
 *
 * The property under test is the one the whole design turns on — **the
 * plaintext never reaches the filesystem**. Everything else here (the op that
 * references the file, the ciphertext hash, the per-file key) follows from
 * doing it in that order.
 */
class MediaStagingTest {

    private val root = File.createTempFile("dcp-media-test", "").let {
        it.delete()
        it.mkdirs()
        it
    }

    @AfterTest
    fun cleanUp() {
        root.deleteRecursively()
    }

    private fun harness(): Triple<MediaStaging, MediaStore, SubmissionStore> {
        val driver = JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        val db = DcpDatabase(driver)
        val submissions = SubmissionStore(db, deviceIdOverride = "dev-media-test")
        val store = MediaStore(db)
        val files = MediaFileStore(root)
        return Triple(MediaStaging(store, files, submissions), store, submissions)
    }

    // A recognisable run in the "photograph", so "none of the original bytes"
    // is a claim about something specific rather than about entropy.
    private val marker = "JFIF-DCP-TEST-MARKER-0123456789".encodeToByteArray()

    private fun photo(size: Int): ByteArray {
        val bytes = ByteArray(size) { ((it * 37 + 11) % 251).toByte() }
        marker.copyInto(bytes)
        return bytes
    }

    private fun crypto(mode: String = SecurityMode.PROJECT_E2E) = ProjectCrypto(
        securityMode = mode,
        projectKeys = listOf(
            ProjectKey(
                keyId = "01PKEYTEST",
                // A real X25519 public key is any 32 bytes that is not a
                // small-order point; the base point works and needs no fixture.
                publicKey = ByteArray(32).also { it[0] = 9 },
                role = "primary",
                label = "Test",
            ),
        ),
    )

    @Test
    fun `a staged file on disk contains none of the original image bytes`() = runBlocking {
        val (staging, _, submissions) = harness()
        val submissionId = submissions.createDraft("housing", 1)
        val plaintext = photo(64 * 1024)

        val staged = staging.stage(
            submissionId, "id_card", "id.jpg", "image/jpeg", plaintext, crypto(),
        )

        val onDisk = File(staged.storageDir).listFiles()!!
            .sortedBy { it.name }
            .fold(ByteArray(0)) { acc, f -> acc + f.readBytes() }

        assertTrue(onDisk.isNotEmpty(), "nothing was written")
        assertFalse(
            onDisk.asList().windowed(marker.size).any { it.toByteArray().contentEquals(marker) },
            "the marker from the original image survived onto the disk",
        )
        // Nor any 32-byte window of the plaintext. This is the check that
        // would catch a key or nonce being reused across chunks, which would
        // leak a repeated plaintext block as a repeated ciphertext block.
        val haystack = onDisk.toList()
        for (offset in 0 until plaintext.size - 32 step 977) {
            val window = plaintext.copyOfRange(offset, offset + 32).toList()
            assertFalse(
                haystack.windowed(32).any { it == window },
                "a 32-byte window of the plaintext at $offset is on disk verbatim",
            )
        }
    }

    @Test
    fun `a staged file decrypts back to exactly what was captured`() = runBlocking {
        val (staging, _, submissions) = harness()
        val submissionId = submissions.createDraft("housing", 1)
        // Two full chunks and a short one, so chunk boundaries and the
        // last-chunk case are both exercised.
        val plaintext = photo(2 * MEDIA_CHUNK_BYTES + 4096)

        val staged = staging.stage(
            submissionId, "roof", "roof.jpg", "image/jpeg", plaintext, crypto(),
        )

        assertEquals(3, staged.chunkCount)
        assertEquals(plaintext.size.toLong(), staged.plaintextSize)
        // Ciphertext is the plaintext plus one 16-byte GCM tag per chunk.
        assertEquals(plaintext.size + 3 * 16L, staged.ciphertextSize)
        assertContentEquals(plaintext, staging.readAll(staged))
    }

    @Test
    fun `the content hash is over ciphertext, so one photograph staged twice differs`() =
        runBlocking {
            val (staging, _, submissions) = harness()
            val submissionId = submissions.createDraft("housing", 1)
            val plaintext = photo(8192)

            val first = staging.stage(
                submissionId, "front", "front.jpg", "image/jpeg", plaintext, crypto(),
            )
            val second = staging.stage(
                submissionId, "back", "back.jpg", "image/jpeg", plaintext, crypto(),
            )

            // Same bytes in, different keys, so different hashes out. Hashing
            // the plaintext would deduplicate nicely and would also let the
            // server confirm that two answers hold the same photograph, which
            // is exactly the inference the mode exists to prevent (§6).
            assertFalse(first.mediaKey.contentEquals(second.mediaKey))
            assertTrue(
                first.ciphertextHash != second.ciphertextHash,
                "identical plaintext produced identical ciphertext hashes",
            )
        }

    @Test
    fun `capturing writes the op that references the file`() = runBlocking {
        val (staging, store, submissions) = harness()
        val submissionId = submissions.createDraft("housing", 1)

        val staged = staging.captureInto(
            submissionId = submissionId,
            formId = "housing",
            formVersion = 1,
            fieldPath = "roof_photo",
            filename = "roof.jpg",
            mimeType = "image/jpeg",
            plaintext = photo(4096),
            crypto = crypto(),
        )

        val answer = submissions.materialisedAnswers(submissionId)["roof_photo"]
        assertEquals(
            FormValue.MediaRef(
                id = staged.mediaId,
                filename = "roof.jpg",
                hash = staged.ciphertextHash,
                size = 4096L,
            ),
            answer,
            "the op's value must be the media reference the server pairs on",
        )
        // And the media row knows which op names it, so the upload can tell the
        // server even when the op value is ciphertext it cannot read.
        assertEquals(
            submissions.opsFor(submissionId).single { it.path == "roof_photo" }.opId,
            store.get(staged.mediaId)!!.opId,
        )
    }

    @Test
    fun `a standard-mode project still encrypts the file on this device`() = runBlocking {
        val (staging, store, submissions) = harness()
        val submissionId = submissions.createDraft("housing", 1)
        val plaintext = photo(4096)

        val staged = staging.stage(
            submissionId, "sign", "sign.jpg", "image/jpeg", plaintext,
            crypto(SecurityMode.STANDARD),
        )

        // `encrypted` is about the UPLOAD: a standard project's server is
        // entitled to read the file. At rest on the phone it is ciphertext
        // regardless — a standard project trusts its own server, which says
        // nothing about the handset left on a clinic desk.
        assertFalse(staged.encrypted)
        assertTrue(store.wrapsFor(staged.mediaId).isEmpty())

        val onDisk = File(staged.storageDir).listFiles()!!.single().readBytes()
        assertFalse(onDisk.contentEquals(plaintext), "the file was staged in the clear")
        assertContentEquals(plaintext, staging.readAll(staged))
    }

    @Test
    fun `an encrypting project with no recipient keys refuses to stage`() = runBlocking {
        val (staging, _, submissions) = harness()
        val submissionId = submissions.createDraft("housing", 1)

        // Wrapping to nobody produces a file nobody — including the people who
        // collected it — can ever open again. Better to refuse the capture.
        val failure = assertFailsWith<EncryptionUnavailableException> {
            staging.stage(
                submissionId, "x", "x.jpg", "image/jpeg", photo(1024),
                ProjectCrypto(SecurityMode.PROJECT_E2E, emptyList()),
            )
        }
        assertTrue(failure.message!!.contains("no active project keys"))
    }

    @Test
    fun `forgetting a capture removes its bytes as well as its row`() = runBlocking {
        val (staging, store, submissions) = harness()
        val submissionId = submissions.createDraft("housing", 1)
        val staged = staging.stage(
            submissionId, "x", "x.jpg", "image/jpeg", photo(1024), crypto(),
        )
        assertNotNull(store.get(staged.mediaId))
        assertTrue(File(staged.storageDir).exists())

        staging.forget(staged.mediaId)

        assertEquals(null, store.get(staged.mediaId))
        assertFalse(File(staged.storageDir).exists(), "the ciphertext was left behind")
    }
}

private fun List<Byte>.toByteArray(): ByteArray = ByteArray(size) { this[it] }
