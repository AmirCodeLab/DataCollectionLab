// Explicit-IV AES-GCM (encryptWithIv/decryptWithIv) is a delicate API because
// caller-managed nonces invite reuse. Our nonces are derived deterministically
// from (deviceId, counter) per spec 4.5 precisely so reuse cannot happen; the
// server additionally rejects a repeated (key_id, nonce) pair.
@file:OptIn(DelicateCryptographyApi::class)

package com.dcp.core.crypto

import dev.whyoleg.cryptography.BinarySize.Companion.bytes
import dev.whyoleg.cryptography.DelicateCryptographyApi
import dev.whyoleg.cryptography.CryptographyProvider
import dev.whyoleg.cryptography.algorithms.AES
import dev.whyoleg.cryptography.algorithms.HKDF
import dev.whyoleg.cryptography.algorithms.SHA256
import dev.whyoleg.cryptography.algorithms.XDH
import dev.whyoleg.cryptography.random.CryptographyRandom
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/**
 * Kotlin implementation of the DCP encryption envelope.
 *
 * The Python module backend/app/modules/crypto/envelope.py is the reference;
 * this implementation must produce byte-identical output for every vector in
 * conformance/crypto. Spec: specs/encryption-envelope-v0.1.md.
 *
 * AAD contents and nonce derivation are normative — never change them here
 * without a spec change, and never without a matching conformance vector.
 *
 * Primitives come from a [CryptographyProvider]: JCA on the JVM, JCA with
 * BouncyCastle on Android (platform JCA lacks X25519 below API 33), CryptoKit
 * on iOS. Same algorithms everywhere: X25519, HKDF-SHA256, AES-256-GCM.
 */

const val ENVELOPE_VERSION: Int = 1

const val CONTENT_KEY_BYTES: Int = 32
const val NONCE_BYTES: Int = 12
const val MEDIA_CHUNK_BYTES: Int = 4 * 1024 * 1024

class EnvelopeException(message: String, cause: Throwable? = null) : Exception(message, cause)

/** A content key wrapped to one recipient project key (spec 4.3). */
class WrappedKey(
    val projectKeyId: String,
    val contentKeyId: String,
    val ephemeralPublic: ByteArray,
    val nonce: ByteArray,
    val wrappedKey: ByteArray,
)

class EncryptedValue(val ciphertext: ByteArray, val nonce: ByteArray)

class EncryptionEnvelope(provider: CryptographyProvider = CryptographyProvider.Default) {

    private val xdh = provider.get(XDH)
    private val aesGcm = provider.get(AES.GCM)
    private val hkdf = provider.get(HKDF)
    private val sha256 = provider.get(SHA256)

    private val wrapInfo = "dcp/v1/wrap".encodeToByteArray()
    private val opNonceInfo = "dcp/v1/op-nonce".encodeToByteArray()
    private val mediaNonceInfo = "dcp/v1/media-nonce".encodeToByteArray()

    // -----------------------------------------------------------------------
    // Nonce derivation (spec 4.5, 6)
    // -----------------------------------------------------------------------

    /**
     * Deterministic per-operation nonce. Safe because each device owns its own
     * content key: a nonce can only repeat if a device reuses a logical
     * counter, which the sync protocol already forbids.
     */
    suspend fun opNonce(deviceId: String, counter: Long): ByteArray {
        if (counter < 0) throw EnvelopeException("counter must be non-negative")
        val material = opNonceInfo + deviceId.encodeToByteArray() + bigEndian(counter)
        return sha256.hasher().hash(material).copyOf(NONCE_BYTES)
    }

    suspend fun mediaNonce(mediaId: String, chunkIndex: Long): ByteArray {
        if (chunkIndex < 0) throw EnvelopeException("chunk index must be non-negative")
        val material = mediaNonceInfo + mediaId.encodeToByteArray() + bigEndian(chunkIndex)
        return sha256.hasher().hash(material).copyOf(NONCE_BYTES)
    }

    // -----------------------------------------------------------------------
    // Key wrapping (spec 4.4)
    // -----------------------------------------------------------------------

    /**
     * Wrap a content key to one recipient.
     *
     * [ephemeralPrivateKey] and [nonce] are injectable so conformance vectors
     * can pin them; production callers must leave both null.
     */
    suspend fun wrapContentKey(
        contentKey: ByteArray,
        contentKeyId: String,
        recipientPublicKey: ByteArray,
        projectKeyId: String,
        ephemeralPrivateKey: ByteArray? = null,
        nonce: ByteArray? = null,
    ): WrappedKey {
        if (contentKey.size != CONTENT_KEY_BYTES) {
            throw EnvelopeException("content key must be $CONTENT_KEY_BYTES bytes")
        }

        val ephemeralPrivate =
            if (ephemeralPrivateKey != null) {
                xdh.privateKeyDecoder(XDH.Curve.X25519)
                    .decodeFromByteArray(XDH.PrivateKey.Format.RAW, ephemeralPrivateKey)
            } else {
                xdh.keyPairGenerator(XDH.Curve.X25519).generateKey().privateKey
            }
        val ephemeralPublic =
            ephemeralPrivate.getPublicKey().encodeToByteArray(XDH.PublicKey.Format.RAW)

        val recipient = xdh.publicKeyDecoder(XDH.Curve.X25519)
            .decodeFromByteArray(XDH.PublicKey.Format.RAW, recipientPublicKey)
        val shared = ephemeralPrivate.sharedSecretGenerator().generateSharedSecretToByteArray(recipient)
        val wrappingKey = wrappingKey(shared, recipientPublicKey, contentKeyId)

        val wrapNonce = nonce ?: CryptographyRandom.nextBytes(NONCE_BYTES)
        val aad = projectKeyId.encodeToByteArray() + contentKeyId.encodeToByteArray()
        val wrapped = aesKey(wrappingKey).cipher().encryptWithIv(wrapNonce, contentKey, aad)

        return WrappedKey(
            projectKeyId = projectKeyId,
            contentKeyId = contentKeyId,
            ephemeralPublic = ephemeralPublic,
            nonce = wrapNonce,
            wrappedKey = wrapped,
        )
    }

    /**
     * Wrap to every active project key (spec 4.3). A lost private key means
     * permanently unrecoverable data; multi-recipient wrapping is the answer.
     */
    suspend fun wrapToRecipients(
        contentKey: ByteArray,
        contentKeyId: String,
        recipients: Map<String, ByteArray>,
    ): List<WrappedKey> {
        if (recipients.isEmpty()) throw EnvelopeException("at least one recipient key is required")
        return recipients.map { (keyId, public) ->
            wrapContentKey(contentKey, contentKeyId, public, keyId)
        }
    }

    suspend fun unwrapContentKey(wrapped: WrappedKey, recipientPrivateKey: ByteArray): ByteArray {
        val private = xdh.privateKeyDecoder(XDH.Curve.X25519)
            .decodeFromByteArray(XDH.PrivateKey.Format.RAW, recipientPrivateKey)
        val recipientPublic = private.getPublicKey().encodeToByteArray(XDH.PublicKey.Format.RAW)

        val ephemeral = xdh.publicKeyDecoder(XDH.Curve.X25519)
            .decodeFromByteArray(XDH.PublicKey.Format.RAW, wrapped.ephemeralPublic)
        val shared = private.sharedSecretGenerator().generateSharedSecretToByteArray(ephemeral)
        val wrappingKey = wrappingKey(shared, recipientPublic, wrapped.contentKeyId)

        val aad = wrapped.projectKeyId.encodeToByteArray() + wrapped.contentKeyId.encodeToByteArray()
        try {
            return aesKey(wrappingKey).cipher().decryptWithIv(wrapped.nonce, wrapped.wrappedKey, aad)
        } catch (cause: Exception) {
            throw EnvelopeException("content key unwrap failed", cause)
        }
    }

    private suspend fun wrappingKey(
        shared: ByteArray,
        recipientPublic: ByteArray,
        contentKeyId: String,
    ): ByteArray =
        hkdf.secretDerivation(
            SHA256,
            CONTENT_KEY_BYTES.bytes,
            recipientPublic,
            wrapInfo + contentKeyId.encodeToByteArray(),
        ).deriveSecretToByteArray(shared)

    // -----------------------------------------------------------------------
    // Operation values (spec 5)
    // -----------------------------------------------------------------------

    /**
     * AAD binds a ciphertext to its exact location. Without `path` a server
     * operator could move an encrypted answer between fields; without
     * `formVersion` a ciphertext could be replayed against a form version
     * where the same path means something else.
     */
    private fun opAad(opId: String, submissionId: String, path: String, formVersion: Int): ByteArray =
        listOf(opId, submissionId, path, formVersion.toString())
            .joinToString("|")
            .encodeToByteArray()

    suspend fun encryptOpValue(
        value: JsonElement,
        contentKey: ByteArray,
        opId: String,
        submissionId: String,
        path: String,
        formVersion: Int,
        deviceId: String,
        counter: Long,
    ): EncryptedValue {
        val nonce = opNonce(deviceId, counter)
        val aad = opAad(opId, submissionId, path, formVersion)
        val ciphertext = aesKey(contentKey).cipher()
            .encryptWithIv(nonce, CanonicalJson.encode(value), aad)
        return EncryptedValue(ciphertext, nonce)
    }

    suspend fun decryptOpValue(
        ciphertext: ByteArray,
        nonce: ByteArray,
        contentKey: ByteArray,
        opId: String,
        submissionId: String,
        path: String,
        formVersion: Int,
    ): JsonElement {
        val aad = opAad(opId, submissionId, path, formVersion)
        val plaintext = try {
            aesKey(contentKey).cipher().decryptWithIv(nonce, ciphertext, aad)
        } catch (cause: Exception) {
            throw EnvelopeException("operation value authentication failed", cause)
        }
        return Json.parseToJsonElement(plaintext.decodeToString())
    }

    // -----------------------------------------------------------------------
    // Media (spec 6)
    // -----------------------------------------------------------------------

    suspend fun encryptMediaChunk(
        chunk: ByteArray,
        mediaKey: ByteArray,
        mediaId: String,
        chunkIndex: Long,
    ): EncryptedValue {
        val nonce = mediaNonce(mediaId, chunkIndex)
        val aad = mediaId.encodeToByteArray() + bigEndian(chunkIndex)
        return EncryptedValue(aesKey(mediaKey).cipher().encryptWithIv(nonce, chunk, aad), nonce)
    }

    suspend fun decryptMediaChunk(
        ciphertext: ByteArray,
        mediaKey: ByteArray,
        mediaId: String,
        chunkIndex: Long,
    ): ByteArray {
        val nonce = mediaNonce(mediaId, chunkIndex)
        val aad = mediaId.encodeToByteArray() + bigEndian(chunkIndex)
        try {
            return aesKey(mediaKey).cipher().decryptWithIv(nonce, ciphertext, aad)
        } catch (cause: Exception) {
            throw EnvelopeException("media chunk authentication failed", cause)
        }
    }

    /**
     * Content address computed over CIPHERTEXT, never plaintext. Hashing
     * plaintext would let the server confirm that two submissions contain the
     * same photograph — exactly the inference this mode exists to prevent.
     */
    fun ciphertextHash(ciphertextChunks: List<ByteArray>): String {
        val hash = sha256.hasher().createHashFunction().use { fn ->
            ciphertextChunks.forEach { fn.update(it) }
            fn.hashToByteArray()
        }
        return hash.joinToString("") { byte -> byte.toUByte().toString(16).padStart(2, '0') }
    }

    // -----------------------------------------------------------------------

    private suspend fun aesKey(raw: ByteArray): AES.GCM.Key =
        aesGcm.keyDecoder().decodeFromByteArray(AES.Key.Format.RAW, raw)

    private fun bigEndian(value: Long): ByteArray =
        ByteArray(8) { i -> (value ushr (8 * (7 - i)) and 0xFF).toByte() }
}
