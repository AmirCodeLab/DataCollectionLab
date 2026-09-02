package com.dcp.core.media

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.crypto.EncryptionEnvelope
import com.dcp.core.crypto.MEDIA_CHUNK_BYTES
import com.dcp.core.db.DcpDatabase
import com.dcp.core.sync.ProjectCrypto
import com.dcp.core.sync.ProjectKey
import com.dcp.core.sync.SecurityMode
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.SyncJson
import com.dcp.core.sync.fixedServerConfig
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.toByteArray
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import java.io.File
import java.util.Properties
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking

/**
 * Resumable upload against a mock server (sync §9).
 *
 * The behaviour that matters is negative: **the chunks the server already holds
 * are not sent again.** On the connections this exists for, re-sending 8 MiB to
 * recover a dropped connection is the difference between an upload that
 * finishes and one that never does.
 */
class MediaUploaderTest {

    private val root = File.createTempFile("dcp-upload-test", "").let {
        it.delete(); it.mkdirs(); it
    }

    @AfterTest
    fun cleanUp() {
        root.deleteRecursively()
    }

    /** Every chunk index the client actually PUT, in order. */
    private val sentChunks = mutableListOf<Int>()
    private val sentBodies = mutableMapOf<Int, ByteArray>()
    private var declaredHash: String? = null
    private var sessionRequests = 0

    private class Harness(
        val uploader: MediaUploader,
        val staging: MediaStaging,
        val store: MediaStore,
        val submissions: SubmissionStore,
        val files: MediaFileStore,
    )

    /**
     * @param alreadyHeld what the server says it has when the session opens —
     *   the state a device meets after an upload was interrupted.
     */
    private fun harness(
        alreadyHeld: List<Int> = emptyList(),
        deleteAfterUpload: Boolean = true,
    ): Harness {
        val driver = JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        val db = DcpDatabase(driver)
        val submissions = SubmissionStore(db, deviceIdOverride = "dev-upload-test")
        val store = MediaStore(db)
        val files = MediaFileStore(root)
        val staging = MediaStaging(store, files, submissions)

        fun MockRequestHandleScope.json(body: String) =
            respond(body, headers = headersOf(HttpHeaders.ContentType, "application/json"))

        val engine = MockEngine { request ->
            val path = request.url.encodedPath
            when {
                path.endsWith("/upload-sessions") -> {
                    sessionRequests++
                    json(
                        """
                        {"uploadId":"upl-1","mediaId":"m","chunkSize":$MEDIA_CHUNK_BYTES,
                         "chunkCount":3,"receivedChunks":${alreadyHeld},
                         "status":"uploading","expiresAt":null}
                        """.trimIndent()
                    )
                }
                path.contains("/chunks/") -> {
                    val index = path.substringAfterLast('/').toInt()
                    sentChunks.add(index)
                    sentBodies[index] = request.body.toByteArray()
                    json(
                        """{"mediaId":"m","chunkIndex":$index,"sizeBytes":1,
                            "receivedChunks":1,"chunkCount":3}"""
                    )
                }
                path.endsWith("/complete") -> {
                    declaredHash = SyncJson
                        .decodeFromString<WireMediaCompleteRequest>(
                            request.body.toByteArray().decodeToString()
                        ).ciphertextHash
                    json(
                        """{"mediaId":"m","hash":"$declaredHash","sizeBytes":1,
                            "chunkCount":3,"status":"complete"}"""
                    )
                }
                else -> respond("unexpected $path", HttpStatusCode.NotFound)
            }
        }
        val http = HttpClient(engine) {
            expectSuccess = true
            install(ContentNegotiation) { json(SyncJson) }
        }

        return Harness(
            MediaUploader(
                store, files, staging, submissions, fixedServerConfig("http://test"), http,
                deleteAfterUpload = deleteAfterUpload,
            ),
            staging, store, submissions, files,
        )
    }

    private fun crypto(mode: String = SecurityMode.PROJECT_E2E) = ProjectCrypto(
        securityMode = mode,
        projectKeys = listOf(
            ProjectKey("01PKEYTEST", ByteArray(32).also { it[0] = 9 }, "primary", "Test"),
        ),
    )

    private fun photo(size: Int) = ByteArray(size) { ((it * 37 + 11) % 251).toByte() }

    /**
     * Two full chunks and a short one, with the project's mode cached in the
     * store — which is what a device that has synced at least once looks like,
     * since SyncClient caches the config before draining media.
     */
    private suspend fun stageThreeChunks(h: Harness, mode: String = SecurityMode.PROJECT_E2E) =
        h.staging.stage(
            h.submissions.createDraft("f", 1),
            "photo", "photo.jpg", "image/jpeg",
            photo(2 * MEDIA_CHUNK_BYTES + 4096),
            crypto(mode),
        ).also { h.submissions.putProjectCrypto(crypto(mode)) }

    @Test
    fun `a fresh upload sends every chunk`() = runBlocking {
        val h = harness()
        val staged = stageThreeChunks(h)

        val result = h.uploader.uploadPending()

        assertEquals(listOf(0, 1, 2), sentChunks)
        assertEquals(3, result.chunksSent)
        assertEquals(0, result.chunksSkipped)
        assertEquals(1, result.filesCompleted)
        assertTrue(h.store.get(staged.mediaId)!!.uploaded)
    }

    @Test
    fun `an interrupted upload resumes without re-sending completed chunks`() = runBlocking {
        // The server already holds 0 and 1: the connection dropped during 2.
        val h = harness(alreadyHeld = listOf(0, 1))
        val staged = stageThreeChunks(h)

        val result = h.uploader.uploadPending()

        assertEquals(
            listOf(2), sentChunks,
            "the client re-sent chunks the server already had",
        )
        assertEquals(1, result.chunksSent)
        assertEquals(2, result.chunksSkipped)
        assertTrue(h.store.get(staged.mediaId)!!.uploaded)
    }

    @Test
    fun `the server's chunk list wins over the device's own record`() = runBlocking {
        // The device believes it uploaded everything; the server has only 0.
        // The server is right — it is the one that decides whether `complete`
        // will succeed — so the client must send 1 and 2 again.
        val h = harness(alreadyHeld = listOf(0))
        val staged = stageThreeChunks(h)
        h.store.replaceChunkState(staged.mediaId, listOf(0, 1, 2))

        h.uploader.uploadPending()

        assertEquals(listOf(1, 2), sentChunks)
    }

    @Test
    fun `an encrypted project uploads the staged ciphertext untouched`() = runBlocking {
        val h = harness(deleteAfterUpload = false)
        val staged = stageThreeChunks(h)

        h.uploader.uploadPending()

        // Byte-for-byte what is on disk. Nothing is re-encrypted on the way
        // out, which is what makes a resumed upload provably identical to the
        // first attempt.
        for (index in 0 until staged.chunkCount) {
            assertContentEquals(
                h.files.read(staged.mediaId, index), sentBodies[index],
                "chunk $index was not sent as staged",
            )
        }
        // And the hash declared is the one computed at capture, over ciphertext.
        assertEquals(staged.ciphertextHash, declaredHash)
    }

    @Test
    fun `a standard-mode project uploads plaintext the server can read`() = runBlocking {
        val h = harness(deleteAfterUpload = false)
        val staged = stageThreeChunks(h, SecurityMode.STANDARD)

        h.uploader.uploadPending()

        val uploaded = (0 until staged.chunkCount)
            .fold(ByteArray(0)) { acc, i -> acc + sentBodies[i]!! }
        assertContentEquals(h.staging.readAll(staged), uploaded)
        // The hash is over what was actually uploaded, so the server's own
        // recomputation agrees with it.
        assertEquals(
            EncryptionEnvelope().ciphertextHash(
                (0 until staged.chunkCount).map { h.staging.readChunk(staged, it) }
            ),
            declaredHash,
        )
        assertFalse(
            staged.ciphertextHash == declaredHash,
            "a standard-mode upload must not declare the at-rest ciphertext hash",
        )
    }

    @Test
    fun `a file captured before the first sync is still uploaded encrypted`() = runBlocking {
        // The leak this test exists for, found on an emulator and not by any
        // test before it. MediaStaging reads the security mode from a local
        // cache; a device that has never synced has none, so the file was
        // staged as "plaintext upload". The operations in the same submission
        // were encrypted — the push path refreshes the config and fails closed
        // — and the photograph went to a project_e2e server in the clear.
        val h = harness(deleteAfterUpload = false)
        val submissionId = h.submissions.createDraft("f", 1)

        // No project crypto cached: this device has never reached the server.
        val staged = h.staging.stage(
            submissionId, "id_card", "id.jpg", "image/jpeg", photo(4096), crypto = null,
        )
        assertFalse(staged.encrypted, "with no cached config, staging cannot know yet")
        assertTrue(h.store.wrapsFor(staged.mediaId).isEmpty())

        // The first sync learns the mode, exactly as SyncClient does before
        // draining media.
        h.submissions.putProjectCrypto(crypto(SecurityMode.PROJECT_E2E))

        h.uploader.uploadPending()

        val after = h.store.get(staged.mediaId)!!
        assertTrue(after.encrypted, "an e2e project must not receive a plaintext file")
        assertEquals(
            1, h.store.wrapsFor(staged.mediaId).size,
            "the media key must be wrapped to the project's recipients",
        )
        // And the bytes on the wire are the staged ciphertext, not plaintext.
        assertContentEquals(h.files.read(staged.mediaId, 0), sentBodies[0])
        assertEquals(staged.ciphertextHash, declaredHash)
    }

    @Test
    fun `a file is not uploaded at all while the security mode is unknown`() = runBlocking {
        // Fail closed. A file left staged is recoverable on the next sync; a
        // plaintext photograph on someone else's server is not.
        val h = harness()
        val submissionId = h.submissions.createDraft("f", 1)
        val staged = h.staging.stage(
            submissionId, "id_card", "id.jpg", "image/jpeg", photo(4096), crypto = null,
        )

        val result = h.uploader.uploadPending()

        assertEquals(1, result.filesFailed)
        assertEquals(0, result.filesCompleted)
        assertEquals(emptyList(), sentChunks, "nothing may leave while the mode is unknown")
        assertFalse(h.store.get(staged.mediaId)!!.uploaded)
        assertTrue(
            h.store.get(staged.mediaId)!!.lastError!!.contains("never fetched"),
            "the reason has to say why it is stuck",
        )
    }

    @Test
    fun `a sealed file's bytes are removed from the device`() = runBlocking {
        val h = harness()
        val staged = stageThreeChunks(h)
        assertTrue(File(staged.storageDir).exists())

        h.uploader.uploadPending()

        assertFalse(
            File(staged.storageDir).exists(),
            "the server has it and it is content-addressed; a phone collecting " +
                "photographs fills up in a week otherwise",
        )
        // The row stays, so the submission can still say which file its op names.
        assertTrue(h.store.get(staged.mediaId)!!.uploaded)
    }

    @Test
    fun `an upload the server already sealed is not sent again`() = runBlocking {
        // The completion response was lost, not the upload.
        val h = harness()
        val staged = stageThreeChunks(h)
        h.uploader.uploadPending()
        sentChunks.clear()

        // A second pass finds nothing pending at all.
        val second = h.uploader.uploadPending()
        assertEquals(0, second.filesCompleted)
        assertEquals(emptyList(), sentChunks)
        assertEquals(0L, h.store.pendingCount())
        assertTrue(h.store.get(staged.mediaId)!!.uploaded)
    }
}