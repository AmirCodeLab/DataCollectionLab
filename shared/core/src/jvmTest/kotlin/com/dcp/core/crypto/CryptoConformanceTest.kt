package com.dcp.core.crypto

/**
 * Runs every crypto conformance vector in conformance/crypto against the
 * Kotlin envelope, asserting byte-identical output with the Python reference
 * that generated them. Any divergence is a release blocker.
 *
 * All key material in the vectors is TEST ONLY and public by design.
 */

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

@OptIn(ExperimentalStdlibApi::class)
@RunWith(Parameterized::class)
class CryptoConformanceTest(@Suppress("unused") private val name: String, private val file: File) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun vectors(): List<Array<Any>> {
            var dir: File? = File(System.getProperty("user.dir")).absoluteFile
            while (dir != null) {
                val candidate = dir.resolve("conformance/crypto")
                if (candidate.isDirectory) {
                    val files = candidate.listFiles { f -> f.extension == "json" }!!.sortedBy { it.name }
                    check(files.isNotEmpty()) { "no crypto conformance vectors found" }
                    return files.map { arrayOf(it.nameWithoutExtension, it) }
                }
                dir = dir.parentFile
            }
            error("conformance/crypto not found above ${System.getProperty("user.dir")}")
        }
    }

    private val envelope = EncryptionEnvelope()

    @Test
    fun vector(): Unit = runBlocking {
        val vector = Json.parseToJsonElement(file.readText()).jsonObject
        assertEquals(ENVELOPE_VERSION, vector.getValue("envelopeVersion").jsonPrimitive.int)

        when (val type = vector.getValue("type").jsonPrimitive.content) {
            "canonical_json" -> checkCanonicalJson(vector)
            "op_nonce" -> checkOpNonce(vector)
            "media_nonce" -> checkMediaNonce(vector)
            "wrap" -> checkWrap(vector)
            "op_value" -> checkOpValue(vector)
            "media" -> checkMedia(vector)
            else -> error("unknown vector type $type")
        }
    }

    private fun cases(vector: JsonObject): List<JsonObject> =
        vector.getValue("cases").jsonArray.map { it.jsonObject }

    private fun JsonObject.str(key: String): String = getValue(key).jsonPrimitive.content
    private fun JsonObject.hex(key: String): ByteArray = str(key).hexToByteArray()
    private fun JsonObject.expected(): JsonObject = getValue("expected").jsonObject

    private fun checkCanonicalJson(vector: JsonObject) {
        for (case in cases(vector)) {
            assertEquals(
                case.str("expected"),
                CanonicalJson.encode(case.getValue("value")).toHexString(),
                "canonical_json[${case.str("name")}]",
            )
        }
    }

    private suspend fun checkOpNonce(vector: JsonObject) {
        for (case in cases(vector)) {
            val deviceId = case.str("deviceId")
            val counter = case.getValue("counter").jsonPrimitive.long
            if (case["expectError"] != null) {
                assertFailsWith<EnvelopeException> { envelope.opNonce(deviceId, counter) }
                continue
            }
            assertEquals(
                case.str("expected"),
                envelope.opNonce(deviceId, counter).toHexString(),
                "opNonce[$deviceId, $counter]",
            )
        }
    }

    private suspend fun checkMediaNonce(vector: JsonObject) {
        for (case in cases(vector)) {
            assertEquals(
                case.str("expected"),
                envelope.mediaNonce(
                    case.str("mediaId"),
                    case.getValue("chunkIndex").jsonPrimitive.long,
                ).toHexString(),
            )
        }
    }

    private suspend fun checkWrap(vector: JsonObject) {
        for (case in cases(vector)) {
            val contentKey = case.hex("contentKey")
            val wrapped = envelope.wrapContentKey(
                contentKey = contentKey,
                contentKeyId = case.str("contentKeyId"),
                recipientPublicKey = case.hex("recipientPublicKey"),
                projectKeyId = case.str("projectKeyId"),
                ephemeralPrivateKey = case.hex("ephemeralPrivateKey"),
                nonce = case.hex("nonce"),
            )
            val expected = case.expected()
            assertEquals(expected.str("ephemeralPublic"), wrapped.ephemeralPublic.toHexString())
            assertEquals(expected.str("wrappedKey"), wrapped.wrappedKey.toHexString())

            val private = case.hex("recipientPrivateKey")
            assertEquals(
                contentKey.toHexString(),
                envelope.unwrapContentKey(wrapped, private).toHexString(),
            )

            for (tamper in case.getValue("tamper").jsonArray.map { it.jsonObject }) {
                val field = tamper.str("field")
                val value = tamper.str("value")
                val tampered = WrappedKey(
                    projectKeyId = if (field == "projectKeyId") value else wrapped.projectKeyId,
                    contentKeyId = if (field == "contentKeyId") value else wrapped.contentKeyId,
                    ephemeralPublic = wrapped.ephemeralPublic,
                    nonce = wrapped.nonce,
                    wrappedKey = wrapped.wrappedKey,
                )
                assertFailsWith<EnvelopeException>("tampered $field must not unwrap") {
                    envelope.unwrapContentKey(tampered, private)
                }
            }
        }
    }

    private suspend fun checkOpValue(vector: JsonObject) {
        for (case in cases(vector)) {
            val name = case.str("name")
            val contentKey = case.hex("contentKey")
            val value = case.getValue("value")
            val opId = case.str("opId")
            val submissionId = case.str("submissionId")
            val path = case.str("path")
            val formVersion = case.getValue("formVersion").jsonPrimitive.int

            val encrypted = envelope.encryptOpValue(
                value = value,
                contentKey = contentKey,
                opId = opId,
                submissionId = submissionId,
                path = path,
                formVersion = formVersion,
                deviceId = case.str("deviceId"),
                counter = case.getValue("counter").jsonPrimitive.long,
            )
            val expected = case.expected()
            assertEquals(expected.str("nonce"), encrypted.nonce.toHexString(), "nonce[$name]")
            assertEquals(
                expected.str("ciphertext"),
                encrypted.ciphertext.toHexString(),
                "ciphertext[$name]",
            )

            val decrypted = envelope.decryptOpValue(
                encrypted.ciphertext, encrypted.nonce, contentKey,
                opId, submissionId, path, formVersion,
            )
            assertEquals(
                CanonicalJson.encode(value).toHexString(),
                CanonicalJson.encode(decrypted).toHexString(),
                "roundtrip[$name]",
            )

            for (tamper in case.getValue("tamper").jsonArray.map { it.jsonObject }) {
                val field = tamper.str("field")
                val value2 = tamper.getValue("value").jsonPrimitive
                assertFailsWith<EnvelopeException>("tampered $field must not decrypt") {
                    envelope.decryptOpValue(
                        encrypted.ciphertext, encrypted.nonce, contentKey,
                        opId = if (field == "opId") value2.content else opId,
                        submissionId = if (field == "submissionId") value2.content else submissionId,
                        path = if (field == "path") value2.content else path,
                        formVersion = if (field == "formVersion") value2.int else formVersion,
                    )
                }
            }
        }
    }

    private suspend fun checkMedia(vector: JsonObject) {
        val mediaKey = vector.hex("mediaKey")
        val mediaId = vector.str("mediaId")
        val ciphertexts = mutableListOf<ByteArray>()
        for (case in vector.getValue("chunks").jsonArray.map { it.jsonObject }) {
            val chunkIndex = case.getValue("chunkIndex").jsonPrimitive.long
            val plaintext = case.hex("plaintext")
            val encrypted = envelope.encryptMediaChunk(plaintext, mediaKey, mediaId, chunkIndex)
            val expected = case.expected()
            assertEquals(expected.str("nonce"), encrypted.nonce.toHexString())
            assertEquals(expected.str("ciphertext"), encrypted.ciphertext.toHexString())
            assertEquals(
                plaintext.toHexString(),
                envelope.decryptMediaChunk(encrypted.ciphertext, mediaKey, mediaId, chunkIndex)
                    .toHexString(),
            )
            // A chunk must not decrypt at a different index. Probed far
            // outside the chunk range: BouncyCastle records the nonce of every
            // cipher init and refuses a later encryption with it, so the probe
            // must never collide with a real chunk's nonce.
            assertFailsWith<EnvelopeException> {
                envelope.decryptMediaChunk(encrypted.ciphertext, mediaKey, mediaId, chunkIndex + 100)
            }
            ciphertexts.add(encrypted.ciphertext)
        }
        assertEquals(vector.str("expectedCiphertextHash"), envelope.ciphertextHash(ciphertexts))
    }
}
