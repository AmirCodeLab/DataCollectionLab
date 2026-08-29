package com.dcp.core.sync

import com.dcp.core.crypto.CONTENT_KEY_BYTES
import com.dcp.core.crypto.EncryptionEnvelope
import com.dcp.core.crypto.EnvelopeException
import com.dcp.core.crypto.Hex
import dev.whyoleg.cryptography.random.CryptographyRandom
import kotlin.time.Clock
import kotlin.time.ExperimentalTime
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull

/**
 * Which fields a form version marks `sensitive` (Form IR §2.1).
 *
 * The client needs this to decide what to encrypt in `field_level` mode. It
 * comes from the compiled form the app already holds; shared/core cannot depend
 * on the app's form catalogue, so the app supplies it.
 */
fun interface FormSensitivity {
    /**
     * Sensitive field ids for a form version, or **null** when this device has
     * no compiled copy of that version.
     *
     * Null is not "nothing is sensitive". A caller that cannot tell must
     * encrypt everything — see [SyncCrypto.shouldEncrypt]. Guessing the other
     * way sends a sensitive answer in the clear exactly once, which is once
     * more than the mode allows.
     */
    suspend fun sensitiveFields(formId: String, formVersion: Int): Set<String>?
}

/** Ops as they leave for the server, with the content keys they need. */
data class PreparedBatch(val ops: List<WireOp>, val keys: List<WireContentKey>)

/**
 * Refused to send. The batch stays in the outbox and the sync fails.
 *
 * Every case here is one where the alternative is pushing a value in the clear
 * that the project's security mode says must be encrypted. A failed sync is
 * recoverable; a plaintext answer on someone else's server is not.
 */
class EncryptionUnavailableException(message: String) : Exception(message)

/**
 * Applies the encryption envelope to outgoing operations
 * (specs/encryption-envelope-v0.1.md §5, driven by the project's security mode).
 *
 * - `standard`: nothing changes, ops go as plaintext.
 * - `field_level`: only the values of fields marked `sensitive` are encrypted;
 *   the rest stay plaintext and stay queryable, which is the whole point of the
 *   mode.
 * - `project_e2e`: every operation value is encrypted.
 *
 * The unit of encryption is the operation VALUE, never the submission: the op
 * log has to stay mergeable, resumable and orderable, and a single blob per
 * submission would destroy all three (§3).
 *
 * Nonces are derived from `(deviceId, counter)` (§4.5), never random, so a
 * retried push re-encrypts to the identical bytes and the server's
 * `(contentKeyId, nonce)` uniqueness check stays a real check rather than a
 * source of spurious rejections.
 */
@OptIn(ExperimentalTime::class)
class SyncCrypto(
    private val store: SubmissionStore,
    private val sensitivity: FormSensitivity,
    private val envelope: EncryptionEnvelope = EncryptionEnvelope(),
    private val random: (Int) -> ByteArray = { CryptographyRandom.nextBytes(it) },
) {

    /**
     * Turns one outbox batch into wire ops, encrypting what the mode requires,
     * and collects the content keys the server does not have yet.
     */
    suspend fun prepare(batch: List<SyncOp>): PreparedBatch {
        val crypto = store.projectCrypto()
        val mode = crypto?.securityMode ?: SecurityMode.STANDARD

        // No cached config yet means the first sync has not completed. Treating
        // that as `standard` is correct only because a project that encrypts
        // gets its mode before its first push: SyncClient fetches the config
        // before draining the outbox.
        if (mode == SecurityMode.STANDARD) {
            return PreparedBatch(batch.map { it.toPlaintextWire() }, emptyList())
        }

        val ops = mutableListOf<WireOp>()
        val keys = linkedMapOf<String, WireContentKey>()
        for (op in batch) {
            if (!shouldEncrypt(op, mode)) {
                ops.add(op.toPlaintextWire())
                continue
            }
            val key = contentKeyFor(op.submissionId, crypto!!)
            ops.add(encrypt(op, key))
            if (!key.uploaded && key.contentKeyId !in keys) {
                keys[key.contentKeyId] = wireKey(key)
            }
        }
        return PreparedBatch(ops, keys.values.toList())
    }

    /**
     * Whether this op's value must be encrypted.
     *
     * An op with no value — `finalize`, `reopen`, `unset`, `repeat_add` — has
     * nothing to encrypt; its path and kind are metadata the server is entitled
     * to read in every mode (§3.1).
     */
    internal suspend fun shouldEncrypt(op: SyncOp, mode: String): Boolean {
        if (op.valueJson == null) return false
        return when (mode) {
            SecurityMode.PROJECT_E2E -> true
            SecurityMode.FIELD_LEVEL -> {
                val path = op.path ?: return false
                // Unknown form version: encrypt. The alternative is deciding
                // "not sensitive" about a field we have never seen.
                val sensitive = sensitivity.sensitiveFields(op.formId, op.formVersion)
                    ?: return true
                referencedFieldOf(path) in sensitive
            }
            else -> false
        }
    }

    /**
     * Encrypts an op's value, or reuses the ciphertext from the last attempt.
     *
     * An op is encrypted exactly once, ever. The nonce comes from
     * `(deviceId, counter)`, so re-deriving would produce identical bytes — but
     * AES-GCM implementations refuse to encrypt twice under one `(key, nonce)`,
     * and rightly so, which would strand a batch that failed to push. Caching
     * the result also means a retry is provably byte-identical rather than
     * merely intended to be.
     */
    private suspend fun encrypt(op: SyncOp, key: ContentKey): WireOp {
        val path = op.path
            ?: throw EncryptionUnavailableException(
                "op ${op.opId} has a value but no path; its AAD cannot be built"
            )
        val ciphertext: String
        val nonce: String
        if (op.valueCiphertext != null && op.nonce != null && op.contentKeyId == key.contentKeyId) {
            ciphertext = op.valueCiphertext
            nonce = op.nonce
        } else {
            val encrypted = envelope.encryptOpValue(
                value = Json.parseToJsonElement(op.valueJson!!),
                contentKey = key.material,
                opId = op.opId,
                submissionId = op.submissionId,
                path = path,
                formVersion = op.formVersion,
                deviceId = op.deviceId,
                counter = op.counter,
            )
            ciphertext = Hex.encode(encrypted.ciphertext)
            nonce = Hex.encode(encrypted.nonce)
            store.recordOpCiphertext(op.opId, ciphertext, key.contentKeyId, nonce)
        }
        return WireOp(
            opId = op.opId,
            submissionId = op.submissionId,
            formId = op.formId,
            formVersion = op.formVersion,
            kind = op.kind,
            path = path,
            // Mutually exclusive with valueCiphertext on the wire (sync §2.1);
            // the server rejects an op carrying both as malformed.
            value = null,
            valueCiphertext = ciphertext,
            contentKeyId = key.contentKeyId,
            nonce = nonce,
            deviceId = op.deviceId,
            actorId = op.actorId,
            counter = op.counter,
            wallClock = op.wallClock,
        )
    }

    /**
     * This device's content key for a submission, generated on first use
     * (envelope §4.2) and wrapped to every active project key (§4.3).
     *
     * Per device rather than per submission so a device receiving a submission
     * from a peer can still add operations to it, holding only the project
     * public key — and so nonces derived from `(deviceId, counter)` cannot
     * collide between devices without any coordination between them.
     */
    private suspend fun contentKeyFor(submissionId: String, crypto: ProjectCrypto): ContentKey {
        store.contentKeyFor(submissionId)?.let { return it }

        if (crypto.projectKeys.isEmpty()) {
            // Wrapping to nobody produces data that nobody — including the
            // people who collected it — can ever read again.
            throw EncryptionUnavailableException(
                "project ${crypto.securityMode} mode has no active project keys to wrap to"
            )
        }

        val material = random(CONTENT_KEY_BYTES)
        val contentKeyId = Ulid.generate(Clock.System.now().toEpochMilliseconds())
        val wraps = try {
            envelope.wrapToRecipients(
                material, contentKeyId, crypto.projectKeys.associate { it.keyId to it.publicKey },
            )
        } catch (cause: EnvelopeException) {
            throw EncryptionUnavailableException(
                "could not wrap a content key for $submissionId: ${cause.message}"
            )
        }

        return store.putContentKey(
            ContentKey(contentKeyId, submissionId, material, uploaded = false),
            wraps.map {
                WrappedKeyRecord(it.projectKeyId, it.ephemeralPublic, it.nonce, it.wrappedKey)
            },
        )
    }

    private fun wireKey(key: ContentKey) = WireContentKey(
        contentKeyId = key.contentKeyId,
        submissionId = key.submissionId,
        deviceId = store.deviceId,
        wraps = store.wrapsFor(key.contentKeyId).map {
            WireWrappedKey(
                projectKeyId = it.projectKeyId,
                ephemeralPublic = Hex.encode(it.ephemeralPublic),
                nonce = Hex.encode(it.nonce),
                wrappedKey = Hex.encode(it.wrappedKey),
            )
        },
    )

    private fun SyncOp.toPlaintextWire() = WireOp(
        opId = opId,
        submissionId = submissionId,
        formId = formId,
        formVersion = formVersion,
        kind = kind,
        path = path,
        value = valueJson?.let { Json.parseToJsonElement(it) },
        deviceId = deviceId,
        actorId = actorId,
        counter = counter,
        wallClock = wallClock,
    )

    companion object {
        /**
         * The field id a value path addresses. `members[i3].age` answers `age`;
         * the repeat is a scope, not a field (Form IR §4.2).
         */
        fun referencedFieldOf(path: String): String =
            if (path.contains("].")) path.substringAfterLast("].") else path
    }
}

/**
 * Decrypts a submission's ops with a project private key (envelope §7).
 *
 * Lives here rather than in the collection app because the readers are the
 * desktop app and the browser: an enumerator's device holds no private key and
 * never needs this path. It is also what an end-to-end test uses to prove the
 * answers survive the round trip.
 */
@OptIn(ExperimentalTime::class)
class SubmissionDecryptor(
    private val envelope: EncryptionEnvelope = EncryptionEnvelope(),
) {

    /**
     * Unwraps every content key this private key can open, keyed by content key
     * id. A submission built by two devices has two content keys, both wrapped
     * to the same recipients, so one private key opens both.
     */
    suspend fun unwrapAll(
        keys: List<WireContentKey>,
        privateKey: ByteArray,
    ): Map<String, ByteArray> {
        val opened = mutableMapOf<String, ByteArray>()
        for (key in keys) {
            for (wrap in key.wraps) {
                val material = runCatching {
                    envelope.unwrapContentKey(
                        com.dcp.core.crypto.WrappedKey(
                            projectKeyId = wrap.projectKeyId,
                            contentKeyId = key.contentKeyId,
                            ephemeralPublic = Hex.decode(wrap.ephemeralPublic),
                            nonce = Hex.decode(wrap.nonce),
                            wrappedKey = Hex.decode(wrap.wrappedKey),
                        ),
                        privateKey,
                    )
                    // A wrap addressed to a different recipient fails to
                    // authenticate, which is the expected outcome, not an error:
                    // it is how a holder finds the wraps that are theirs.
                }.getOrNull()
                if (material != null) {
                    opened[key.contentKeyId] = material
                    break
                }
            }
        }
        return opened
    }

    /**
     * Folds ops into current answers, decrypting as it goes.
     *
     * Same fold as everywhere else — last writer wins by `(counter, deviceId)`
     * — so a decrypted view and the enumerator's own view of a submission
     * cannot disagree.
     */
    suspend fun answers(
        ops: List<WirePulledOp>,
        contentKeys: Map<String, ByteArray>,
    ): Map<String, kotlinx.serialization.json.JsonElement> {
        val values = LinkedHashMap<String, kotlinx.serialization.json.JsonElement>()
        for (op in ops.sortedWith(compareBy({ it.counter }, { it.deviceId }))) {
            val path = op.path ?: continue
            when (op.kind) {
                OpKind.UNSET -> values.remove(path)
                OpKind.SET -> {
                    val ciphertext = op.valueCiphertext
                    if (ciphertext == null) {
                        values[path] = op.value ?: JsonNull
                        continue
                    }
                    val key = op.contentKeyId?.let(contentKeys::get)
                        ?: throw EnvelopeException(
                            "no content key for op ${op.opId} (${op.contentKeyId})"
                        )
                    values[path] = envelope.decryptOpValue(
                        ciphertext = Hex.decode(ciphertext),
                        nonce = Hex.decode(op.nonce ?: ""),
                        contentKey = key,
                        opId = op.opId,
                        submissionId = op.submissionId,
                        path = path,
                        formVersion = op.formVersion,
                    )
                }
            }
        }
        return values
    }
}
