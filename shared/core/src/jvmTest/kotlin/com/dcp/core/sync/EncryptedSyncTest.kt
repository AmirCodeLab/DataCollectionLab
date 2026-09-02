package com.dcp.core.sync

/**
 * The client half of encrypted sync (encryption envelope §5, sync §2.1).
 *
 * The server is a mock that records exactly what left the device, which is the
 * point: these tests assert on the bytes on the wire, not on an intention. The
 * matching server-side round trip against real Postgres lives in
 * backend/tests/test_encrypted_sync.py.
 */

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.crypto.EncryptionEnvelope
import com.dcp.core.crypto.Hex
import com.dcp.core.db.DcpDatabase
import com.dcp.form.FormValue
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.content.TextContent
import io.ktor.http.HttpHeaders
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.encodeToJsonElement

private const val DEVICE = "dev-crypto-test"
private const val FORM = "clinic_intake"

/** TEST ONLY, generated per run. Stands in for a project key holder. */
private class TestRecipient(val keyId: String) {
    private val generator = java.security.KeyPairGenerator.getInstance("X25519")
    private val pair = generator.generateKeyPair()

    /** Raw 32 bytes: X25519 SubjectPublicKeyInfo is a 12-byte header + the key. */
    val publicKey: ByteArray = pair.public.encoded.copyOfRange(12, 44)

    /** Raw 32 bytes: PKCS#8 for X25519 is a 16-byte header + the scalar. */
    val privateKey: ByteArray = pair.private.encoded.let { it.copyOfRange(it.size - 32, it.size) }
}

/**
 * Fields that are opaque by construction: ciphertext, nonces and the ids that
 * name them. Nothing readable is in here, so nothing in here is searched.
 *
 * A field added to any wire type is checked by DEFAULT — it has to be named
 * here to be exempt, and the only things that earn an exemption are bytes no
 * key on the server opens.
 */
private val OPAQUE_FIELDS = setOf(
    "valueCiphertext",
    "nonce",
    "contentKeyId",
    "ephemeralPublic",
    "wrappedKey",
)

/**
 * Every JSON leaf of a pushed object that the server can actually read.
 *
 * Walking the parsed object is the point. The obvious test — serialise the
 * push and assert an answer is not a substring of it — is not a test at all
 * for a short answer made of hex digits: "412" appears in a blob of random hex
 * about half the time, so that assertion passed by luck and would have failed
 * on some future run for no reason. Comparing whole leaves has no such
 * accident in it: a leaked value is its own leaf, and metadata that merely
 * contains the same digits (a wall clock ending .412Z, a ULID with 412 in it)
 * is not a leak and no longer pretends to be one.
 */
private fun readableLeaves(
    element: JsonElement,
    out: MutableList<String> = mutableListOf(),
): List<String> {
    when (element) {
        is JsonObject -> element.forEach { (name, child) ->
            if (name !in OPAQUE_FIELDS) readableLeaves(child, out)
        }
        is JsonArray -> element.forEach { readableLeaves(it, out) }
        is JsonPrimitive -> out.add(element.content)
    }
    return out
}

/** The mock server: remembers what was pushed so a test can inspect it. */
private class RecordingServer(private val securityMode: String, val recipients: List<TestRecipient>) {
    val pushes = mutableListOf<WirePushRequest>()

    val ops: List<WireOp> get() = pushes.flatMap { it.ops }
    val keys: List<WireContentKey> get() = pushes.flatMap { it.keys }

    fun client(): HttpClient = HttpClient(
        MockEngine { request ->
            val body = { text: String ->
                respond(text, headers = headersOf(HttpHeaders.ContentType, "application/json"))
            }
            when {
                request.url.encodedPath.endsWith("/crypto") -> body(
                    """{"deviceId":"$DEVICE","projectId":"prj","securityMode":"$securityMode",
                        "projectKeys":[${recipients.joinToString(",") {
                        """{"keyId":"${it.keyId}","publicKey":"${Hex.encode(it.publicKey)}",
                            "role":"primary","label":"holder"}"""
                    }}]}"""
                )
                request.url.encodedPath.endsWith("/devices") ->
                    body("""{"deviceId":"$DEVICE","status":"registered"}""")
                request.url.encodedPath.endsWith("/push") -> {
                    val push = SyncJson.decodeFromString(
                        WirePushRequest.serializer(), (request.body as TextContent).text
                    )
                    pushes.add(push)
                    body(
                        """{"accepted":[${push.ops.joinToString(",") { "\"${it.opId}\"" }}],
                            "rejected":[],"serverCursor":1}"""
                    )
                }
                else -> body("""{"ops":[],"tombstones":[],"nextCursor":0,"hasMore":false}""")
            }
        }
    ) {
        expectSuccess = true
        install(ContentNegotiation) { json(SyncJson) }
    }
}

class EncryptedSyncTest {

    private fun store() = SubmissionStore(
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)),
        deviceIdOverride = DEVICE,
    )

    /** Field ids the test form marks `sensitive` (Form IR §2.1). */
    private val sensitive = FormSensitivity { formId, version ->
        if (formId == FORM && version == 1) setOf("hiv_status", "cd4_count") else null
    }

    @Test
    fun `project_e2e encrypts every value and the answers survive the round trip`(): Unit = runBlocking {
        val holder = TestRecipient("01PKEYA")
        val backup = TestRecipient("01PKEYB")
        val server = RecordingServer(SecurityMode.PROJECT_E2E, listOf(holder, backup))
        val store = store()

        val submission = store.createDraft(FORM, 1)
        val answers = mapOf(
            "patient_name" to FormValue.Text("Amina Yusuf"),
            "hiv_status" to FormValue.Text("positive"),
            "cd4_count" to FormValue.Integer(412),
            "clinic_code" to FormValue.Text("KLA-07"),
        )
        answers.forEach { (path, value) ->
            store.appendOp(submission, FORM, 1, OpKind.SET, path, value)
        }
        store.appendOp(submission, FORM, 1, OpKind.FINALIZE)

        val result = SyncClient(
            store, { "http://test" }, httpClient = server.client(), formSensitivity = sensitive,
        ).syncOnce()

        assertNull(result.error)
        assertEquals(5, result.pushedOps)

        // Every value op left as ciphertext, and none of them carried a value.
        val valueOps = server.ops.filter { it.kind == OpKind.SET }
        assertEquals(4, valueOps.size)
        valueOps.forEach { op ->
            assertNotNull(op.valueCiphertext, "${op.path} was pushed without ciphertext")
            assertNull(op.value, "${op.path} was pushed with a plaintext value")
            assertNotNull(op.contentKeyId)
            assertEquals(12, Hex.decode(op.nonce!!).size)
        }

        // An op with no value has nothing to encrypt; its metadata is readable
        // by design (§3.1) and finalisation must still reach the server.
        val finalize = server.ops.single { it.kind == OpKind.FINALIZE }
        assertNull(finalize.valueCiphertext)
        assertNull(finalize.contentKeyId)

        // No answer appears as a value anywhere the server can read — in any
        // field of any op or key, including fields nobody has added yet.
        val readable = readableLeaves(
            SyncJson.encodeToJsonElement(WirePushRequest.serializer(), server.pushes.single()),
        )
        listOf("Amina Yusuf", "positive", "KLA-07", "412").forEach {
            assertFalse(it in readable, "'$it' left the device in the clear, among $readable")
        }

        // One content key for this submission, wrapped to both recipients.
        val key = server.keys.single()
        assertEquals(submission, key.submissionId)
        assertEquals(DEVICE, key.deviceId)
        assertEquals(setOf("01PKEYA", "01PKEYB"), key.wraps.map { it.projectKeyId }.toSet())

        // A key holder gets the original answers back.
        val decryptor = SubmissionDecryptor()
        val opened = decryptor.unwrapAll(server.keys, holder.privateKey)
        assertEquals(setOf(key.contentKeyId), opened.keys)
        assertEquals(
            mapOf(
                "patient_name" to JsonPrimitive("Amina Yusuf"),
                "hiv_status" to JsonPrimitive("positive"),
                "cd4_count" to JsonPrimitive(412),
                "clinic_code" to JsonPrimitive("KLA-07"),
            ),
            decryptor.answers(server.ops.map { it.asPulled() }, opened),
        )

        // So does the backup holder, from the same stored wraps (§4.3)...
        assertEquals(
            opened.values.single().toList(),
            decryptor.unwrapAll(server.keys, backup.privateKey).values.single().toList(),
        )
        // ...and nobody else.
        assertTrue(decryptor.unwrapAll(server.keys, TestRecipient("other").privateKey).isEmpty())
    }

    @Test
    fun `field_level encrypts only the sensitive fields`(): Unit = runBlocking {
        val holder = TestRecipient("01PKEYA")
        val server = RecordingServer(SecurityMode.FIELD_LEVEL, listOf(holder))
        val store = store()

        val submission = store.createDraft(FORM, 1)
        store.appendOp(submission, FORM, 1, OpKind.SET, "clinic_code", FormValue.Text("KLA-07"))
        store.appendOp(submission, FORM, 1, OpKind.SET, "hiv_status", FormValue.Text("positive"))
        store.appendOp(submission, FORM, 1, OpKind.SET, "cd4_count", FormValue.Integer(412))

        assertNull(
            SyncClient(
                store, { "http://test" }, httpClient = server.client(), formSensitivity = sensitive,
            ).syncOnce().error
        )

        val byPath = server.ops.associateBy { it.path }
        // The non-sensitive remainder stays plaintext and stays queryable —
        // that is the whole reason field_level exists (envelope §1).
        assertEquals(JsonPrimitive("KLA-07"), byPath.getValue("clinic_code").value)
        assertNull(byPath.getValue("clinic_code").valueCiphertext)
        // The sensitive fields do not.
        listOf("hiv_status", "cd4_count").forEach {
            assertNull(byPath.getValue(it).value)
            assertNotNull(byPath.getValue(it).valueCiphertext)
        }

        val decryptor = SubmissionDecryptor()
        val opened = decryptor.unwrapAll(server.keys, holder.privateKey)
        // The fold mixes both halves back into one set of answers.
        assertEquals(
            mapOf(
                "clinic_code" to JsonPrimitive("KLA-07"),
                "hiv_status" to JsonPrimitive("positive"),
                "cd4_count" to JsonPrimitive(412),
            ),
            decryptor.answers(server.ops.map { it.asPulled() }, opened),
        )
    }

    @Test
    fun `a repeat path resolves to its field, so members income is still encrypted`(): Unit =
        runBlocking {
            val server = RecordingServer(SecurityMode.FIELD_LEVEL, listOf(TestRecipient("01PKEYA")))
            val store = store()
            val submission = store.createDraft(FORM, 1)
            store.appendOp(
                submission, FORM, 1, OpKind.SET, "members[i3].income", FormValue.Integer(900),
            )
            store.appendOp(
                submission, FORM, 1, OpKind.SET, "members[i3].village", FormValue.Text("Kira"),
            )

            val repeatAware = FormSensitivity { _, _ -> setOf("income") }
            assertNull(
                SyncClient(
                    store, { "http://test" }, httpClient = server.client(),
                    formSensitivity = repeatAware,
                ).syncOnce().error
            )

            val byPath = server.ops.associateBy { it.path }
            // Resolving the path to `members` would have sent this in the clear.
            assertNotNull(byPath.getValue("members[i3].income").valueCiphertext)
            assertNull(byPath.getValue("members[i3].village").valueCiphertext)
        }

    @Test
    fun `field_level encrypts everything when the form version is unknown`(): Unit = runBlocking {
        val server = RecordingServer(SecurityMode.FIELD_LEVEL, listOf(TestRecipient("01PKEYA")))
        val store = store()
        val submission = store.createDraft(FORM, 1)
        store.appendOp(submission, FORM, 1, OpKind.SET, "clinic_code", FormValue.Text("KLA-07"))

        // A device that has not compiled this form version cannot tell which
        // fields are sensitive. Guessing "none" sends a sensitive answer in the
        // clear exactly once, which is once more than the mode allows.
        assertNull(
            SyncClient(
                store, { "http://test" }, httpClient = server.client(),
                formSensitivity = FormSensitivity { _, _ -> null },
            ).syncOnce().error
        )

        assertNotNull(server.ops.single().valueCiphertext)
    }

    @Test
    fun `standard mode changes nothing`(): Unit = runBlocking {
        val server = RecordingServer(SecurityMode.STANDARD, emptyList())
        val store = store()
        val submission = store.createDraft(FORM, 1)
        store.appendOp(submission, FORM, 1, OpKind.SET, "hiv_status", FormValue.Text("positive"))

        assertNull(
            SyncClient(
                store, { "http://test" }, httpClient = server.client(), formSensitivity = sensitive,
            ).syncOnce().error
        )

        assertEquals(JsonPrimitive("positive"), server.ops.single().value)
        assertNull(server.ops.single().valueCiphertext)
        assertTrue(server.keys.isEmpty())
    }

    @Test
    fun `a project with no keys to wrap to refuses to push rather than send plaintext`(): Unit =
        runBlocking {
            // Wrapping to nobody produces data nobody can ever read again, and
            // sending it unencrypted breaks the guarantee the mode exists for.
            // The only safe answer is to keep it on the device.
            val server = RecordingServer(SecurityMode.PROJECT_E2E, emptyList())
            val store = store()
            val submission = store.createDraft(FORM, 1)
            store.appendOp(submission, FORM, 1, OpKind.SET, "hiv_status", FormValue.Text("positive"))

            val result = SyncClient(
                store, { "http://test" }, httpClient = server.client(), formSensitivity = sensitive,
            ).syncOnce()

            assertNotNull(result.error)
            assertEquals(0, result.pushedOps)
            assertTrue(server.ops.isEmpty(), "an op left the device unencrypted")
            assertEquals(1, store.pendingCount())
        }

    @Test
    fun `a push that failed sends the identical bytes when it is retried`(): Unit = runBlocking {
        // An op is encrypted once, ever. The nonce is derived from
        // (deviceId, counter), never random (§4.5), so re-deriving would give
        // the same bytes — but AES-GCM refuses to encrypt twice under one
        // (key, nonce), so a rejected batch that re-encrypted would be stranded
        // for the life of the process. The stored ciphertext removes the
        // question, and makes retry byte-identical rather than merely intended
        // to be.
        val server = RecordingServer(SecurityMode.PROJECT_E2E, listOf(TestRecipient("01PKEYA")))
        val store = store()
        val submission = store.createDraft(FORM, 1)
        store.appendOp(submission, FORM, 1, OpKind.SET, "hiv_status", FormValue.Text("positive"))

        val crypto = SyncCrypto(store, sensitive)
        SyncClient(
            store, { "http://test" }, httpClient = server.client(), formSensitivity = sensitive,
        ).syncOnce()

        // As if the server had never answered: the op is pending again.
        store.markPushResult(emptyList(), listOf(RejectedPush(server.ops.single().opId, "malformed")))
        store.requeueRejectedOps()

        val again = crypto.prepare(store.pendingOps(10)).ops.single()
        val first = server.ops.single()
        assertEquals(first.valueCiphertext, again.valueCiphertext)
        assertEquals(first.nonce, again.nonce)
        assertEquals(first.contentKeyId, again.contentKeyId)

        // And the enumerator still sees their own answer: the cached ciphertext
        // sits beside the plaintext, it does not replace it.
        assertEquals(
            FormValue.Text("positive"),
            store.materialisedAnswers(submission)["hiv_status"],
        )
    }

    @Test
    fun `a content key is uploaded once, then stops riding every batch`(): Unit = runBlocking {
        val server = RecordingServer(SecurityMode.PROJECT_E2E, listOf(TestRecipient("01PKEYA")))
        val store = store()
        val submission = store.createDraft(FORM, 1)
        store.appendOp(submission, FORM, 1, OpKind.SET, "hiv_status", FormValue.Text("positive"))

        val client = SyncClient(
            store, { "http://test" }, httpClient = server.client(), formSensitivity = sensitive,
        )
        client.syncOnce()
        assertEquals(1, server.keys.size)

        // A correction to the same submission reuses the key the server has.
        store.appendOp(submission, FORM, 1, OpKind.SET, "hiv_status", FormValue.Text("negative"))
        client.syncOnce()

        assertEquals(1, server.keys.size, "the key was re-sent after the server acknowledged it")
        assertEquals(
            server.ops[0].contentKeyId,
            server.ops[1].contentKeyId,
            "a correction must encrypt under the same key as the answer it replaces",
        )
    }

    @Test
    fun `an encrypted op pulled from another device is not folded in as null`(): Unit = runBlocking {
        // This device holds no private key, so it cannot read a peer's answer.
        // Folding it as Null would claim the field was answered blank, which is
        // a different and false statement about someone's data.
        val store = store()
        val envelope = EncryptionEnvelope()
        val submission = store.createDraft(FORM, 1)
        store.appendOp(submission, FORM, 1, OpKind.SET, "clinic_code", FormValue.Text("KLA-07"))

        val material = ByteArray(32) { it.toByte() }
        val encrypted = envelope.encryptOpValue(
            JsonPrimitive("positive"), material, "01OPPEER", submission, "hiv_status", 1,
            "dev-peer", 1,
        )
        store.applyPullBatch(
            listOf(
                SyncOp(
                    opId = "01OPPEER", submissionId = submission, formId = FORM, formVersion = 1,
                    kind = OpKind.SET, path = "hiv_status", valueJson = null,
                    deviceId = "dev-peer", actorId = "usr-peer", counter = 1,
                    wallClock = "2026-08-29T10:00:00Z", synced = true,
                    valueCiphertext = Hex.encode(encrypted.ciphertext),
                    contentKeyId = "01CKPEER", nonce = Hex.encode(encrypted.nonce),
                )
            ),
            nextCursor = 12,
        )

        val answers = store.materialisedAnswers(submission)
        assertEquals(FormValue.Text("KLA-07"), answers["clinic_code"])
        assertFalse("hiv_status" in answers, "an unreadable answer was folded in as a value")

        // The ciphertext is kept, not discarded: a key holder opens it later.
        val stored = store.opsFor(submission).single { it.opId == "01OPPEER" }
        assertTrue(stored.isEncrypted)
        assertEquals(
            mapOf("hiv_status" to JsonPrimitive("positive")),
            SubmissionDecryptor().answers(
                listOf(
                    WirePulledOp(
                        opId = stored.opId, submissionId = submission, formId = FORM,
                        formVersion = 1, kind = OpKind.SET, path = "hiv_status",
                        valueCiphertext = stored.valueCiphertext, contentKeyId = "01CKPEER",
                        nonce = stored.nonce, deviceId = "dev-peer", counter = 1,
                        wallClock = stored.wallClock, serverSeq = 1,
                    )
                ),
                mapOf("01CKPEER" to material),
            ),
        )
    }
}

/** The wire op as it comes back from a pull, for the decrypt-side assertions. */
private fun WireOp.asPulled() = WirePulledOp(
    opId = opId,
    submissionId = submissionId,
    formId = formId,
    formVersion = formVersion,
    kind = kind,
    path = path,
    value = value,
    valueCiphertext = valueCiphertext,
    contentKeyId = contentKeyId,
    nonce = nonce,
    deviceId = deviceId,
    actorId = actorId,
    counter = counter,
    wallClock = wallClock,
    serverSeq = counter,
)
