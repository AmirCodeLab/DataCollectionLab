package com.dcp.core.sync

import app.cash.sqldelight.coroutines.asFlow
import app.cash.sqldelight.coroutines.mapToList
import com.dcp.core.crypto.Hex
import com.dcp.core.db.DcpDatabase
import com.dcp.form.FormValue
import com.dcp.form.formValueFromJson
import com.dcp.form.formValueToJson
import kotlin.coroutines.CoroutineContext
import kotlin.random.Random
import kotlin.time.Clock
import kotlin.time.ExperimentalTime
import kotlin.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** Operation kinds, sync protocol §2. */
object OpKind {
    const val SET = "set"
    const val UNSET = "unset"
    const val FINALIZE = "finalize"
    const val REOPEN = "reopen"
}

object SubmissionStatus {
    const val DRAFT = "draft"
    const val FINALIZED = "finalized"
}

/** One operation, exactly the shape the push endpoint takes (sync protocol §2). */
data class SyncOp(
    val opId: String,
    val submissionId: String,
    val formId: String,
    val formVersion: Int,
    val kind: String,
    val path: String?,
    val valueJson: String?,
    val deviceId: String,
    val actorId: String,
    val counter: Long,
    val wallClock: String,
    val synced: Boolean,
    /** Why the server refused this op, kept until it is accepted on a retry. */
    val rejectReason: String? = null,
    /**
     * Set only on ops pulled from another device in an encrypted project
     * (sync §2.1), lowercase hex. This device holds no private key, so these
     * stay opaque here — [SubmissionDecryptor] opens them where a key holder
     * is present. Ops this device wrote carry [valueJson] instead and are
     * encrypted on the way out.
     */
    val valueCiphertext: String? = null,
    val contentKeyId: String? = null,
    val nonce: String? = null,
) {
    val isEncrypted: Boolean get() = valueCiphertext != null
}

/** The server's verdict on one rejected op from a push response. */
data class RejectedPush(val opId: String, val reason: String)

/** Ops the server refuses to store, grouped by its stated reason. */
data class RejectedOpGroup(val reason: String, val count: Long)

data class SubmissionSummary(
    val submissionId: String,
    val formId: String,
    val formVersion: Int,
    val status: String,
    val createdAt: String,
    val updatedAt: String,
    val pendingOps: Long,
)

data class SyncStatus(
    val pullCursor: Long,
    val lastSyncAt: String?,
    val lastError: String?,
)

/** One recipient a content key is wrapped to (encryption envelope §4.1). */
data class ProjectKey(
    val keyId: String,
    /** X25519 public key, 32 bytes. Public — there is nothing secret here. */
    val publicKey: ByteArray,
    val role: String,
    val label: String,
) {
    // ByteArray gives identity equality, which would make two equal key sets
    // compare unequal and quietly re-wrap on every sync.
    override fun equals(other: Any?): Boolean =
        this === other ||
            (other is ProjectKey &&
                keyId == other.keyId &&
                publicKey.contentEquals(other.publicKey) &&
                role == other.role &&
                label == other.label)

    override fun hashCode(): Int =
        ((keyId.hashCode() * 31 + publicKey.contentHashCode()) * 31 + role.hashCode()) * 31 +
            label.hashCode()
}

/**
 * The project's security mode and current recipient set (sync §4).
 *
 * [SecurityMode] decides what gets encrypted; the keys decide who can ever read
 * it again. Both come from the server and are cached locally so a device keeps
 * encrypting through however long it is offline.
 */
data class ProjectCrypto(val securityMode: String, val projectKeys: List<ProjectKey>)

object SecurityMode {
    const val STANDARD = "standard"
    const val FIELD_LEVEL = "field_level"
    const val PROJECT_E2E = "project_e2e"
}

/**
 * This device's content key for one submission (envelope §4.2).
 *
 * [material] never leaves the device. [wraps] are the copies that do — one per
 * active project key, openable only with a private key the server has never
 * held.
 */
data class WrappedKeyRecord(
    val projectKeyId: String,
    val ephemeralPublic: ByteArray,
    val nonce: ByteArray,
    val wrappedKey: ByteArray,
) {
    override fun equals(other: Any?): Boolean =
        this === other ||
            (other is WrappedKeyRecord &&
                projectKeyId == other.projectKeyId &&
                ephemeralPublic.contentEquals(other.ephemeralPublic) &&
                nonce.contentEquals(other.nonce) &&
                wrappedKey.contentEquals(other.wrappedKey))

    override fun hashCode(): Int =
        ((projectKeyId.hashCode() * 31 + ephemeralPublic.contentHashCode()) * 31 +
            nonce.contentHashCode()) * 31 + wrappedKey.contentHashCode()
}

/** How a [ProjectKey] is held in the single-row cache. Hex, so it is legible. */
@Serializable
private data class StoredProjectKey(
    val keyId: String,
    val publicKey: String,
    val role: String,
    val label: String,
) {
    fun toProjectKey() = ProjectKey(keyId, Hex.decode(publicKey), role, label)

    companion object {
        fun from(key: ProjectKey) =
            StoredProjectKey(key.keyId, Hex.encode(key.publicKey), key.role, key.label)
    }
}

data class ContentKey(
    val contentKeyId: String,
    val submissionId: String,
    val material: ByteArray,
    val uploaded: Boolean,
) {
    override fun equals(other: Any?): Boolean =
        this === other ||
            (other is ContentKey &&
                contentKeyId == other.contentKeyId &&
                submissionId == other.submissionId &&
                material.contentEquals(other.material) &&
                uploaded == other.uploaded)

    override fun hashCode(): Int =
        ((contentKeyId.hashCode() * 31 + submissionId.hashCode()) * 31 +
            material.contentHashCode()) * 31 + uploaded.hashCode()
}

/**
 * Local submission store and operation outbox.
 *
 * Answers are never persisted materialised: every change is an operation with a
 * per-device monotonic counter (never reset — it lives in `device_state`, not in
 * memory), and reopening a draft folds its op log back into a value map in
 * `(counter, deviceId)` order. This is the same fold the server performs, so
 * local state and server state cannot drift.
 */
@OptIn(ExperimentalTime::class)
class SubmissionStore(
    db: DcpDatabase,
    private val actorId: String = "usr_local",
    private val now: () -> Instant = { Clock.System.now() },
    /** Fixed device identity (registration/tests); default is a generated one. */
    deviceIdOverride: String? = null,
) {
    private val queries = db.syncQueries
    val deviceId: String

    init {
        val candidate = deviceIdOverride ?: ("dev_" + buildString {
            repeat(8) { append("0123456789abcdef"[Random.nextInt(16)]) }
        })
        queries.initDeviceState(candidate) // INSERT OR IGNORE: first launch only
        queries.initSyncStatus()
        deviceId = queries.getDeviceState().executeAsOne().device_id
    }

    fun createDraft(formId: String, formVersion: Int): String {
        val instant = now()
        val id = Ulid.generate(instant.toEpochMilliseconds())
        val iso = instant.toString()
        queries.insertSubmission(id, formId, formVersion.toLong(), iso, iso)
        return id
    }

    fun appendOp(
        submissionId: String,
        formId: String,
        formVersion: Int,
        kind: String,
        path: String? = null,
        value: FormValue? = null,
    ): SyncOp = queries.transactionWithResult {
        val instant = now()
        queries.bumpCounter()
        val device = queries.getDeviceState().executeAsOne()
        val op = SyncOp(
            opId = Ulid.generate(instant.toEpochMilliseconds()),
            submissionId = submissionId,
            formId = formId,
            formVersion = formVersion,
            kind = kind,
            path = path,
            valueJson = value?.let { formValueToJson(it).toString() },
            deviceId = device.device_id,
            actorId = actorId,
            counter = device.counter,
            wallClock = instant.toString(),
            synced = false,
        )
        queries.insertOp(
            op.opId, op.submissionId, op.formId, op.formVersion.toLong(), op.kind,
            op.path, op.valueJson, op.deviceId, op.actorId, op.counter, op.wallClock,
        )
        queries.touchSubmission(op.wallClock, submissionId)
        if (kind == OpKind.FINALIZE) {
            queries.setSubmissionStatus(SubmissionStatus.FINALIZED, op.wallClock, submissionId)
        }
        if (kind == OpKind.REOPEN) {
            queries.setSubmissionStatus(SubmissionStatus.DRAFT, op.wallClock, submissionId)
        }
        op
    }

    private fun toSyncOp(it: com.dcp.core.db.Op_outbox): SyncOp = SyncOp(
        opId = it.op_id,
        submissionId = it.submission_id,
        formId = it.form_id,
        formVersion = it.form_version.toInt(),
        kind = it.kind,
        path = it.path,
        valueJson = it.value_json,
        deviceId = it.device_id,
        actorId = it.actor_id,
        counter = it.counter,
        wallClock = it.wall_clock,
        synced = it.synced == 1L,
        rejectReason = it.reject_reason,
        valueCiphertext = it.value_ciphertext,
        contentKeyId = it.content_key_id,
        nonce = it.nonce,
    )

    fun opsFor(submissionId: String): List<SyncOp> =
        queries.opsForSubmission(submissionId).executeAsList().map(::toSyncOp)

    // -- outbox / sync -----------------------------------------------------

    /** Oldest unpushed ops, up to [limit] — one push batch. */
    fun pendingOps(limit: Int): List<SyncOp> =
        queries.pendingOps(limit.toLong()).executeAsList().map(::toSyncOp)

    fun pendingCount(): Long = queries.countPendingOps().executeAsOne()

    /**
     * Records the server's verdict on a pushed batch. ONLY ops the server
     * accepted leave the outbox; a rejected op stays in it with the server's
     * reason, and anything the server never mentioned stays plain-pending —
     * both are retried, so a push can neither lose nor duplicate an op
     * (replays are idempotent by opId, sync §4).
     */
    fun markPushResult(accepted: List<String>, rejected: List<RejectedPush>) =
        queries.transaction {
            accepted.forEach { queries.markOpSynced(it) }
            rejected.forEach { queries.markOpRejected(it.reason, it.opId) }
        }

    /**
     * Returns rejected ops to the pending set so the next sync retries them
     * (an op can be rejected transiently — e.g. before its form version is
     * published). Their reject_reason is kept until the server accepts them.
     */
    fun requeueRejectedOps() = queries.requeueRejectedOps()

    fun rejectedOpSummary(): List<RejectedOpGroup> =
        queries.rejectedOpSummary().executeAsList()
            .map { RejectedOpGroup(it.reject_reason, it.op_count) }

    fun observeRejectedOpSummary(
        context: CoroutineContext = Dispatchers.Default,
    ): Flow<List<RejectedOpGroup>> =
        queries.rejectedOpSummary().asFlow().mapToList(context).map { rows ->
            rows.map { RejectedOpGroup(it.reject_reason, it.op_count) }
        }

    // -- encryption envelope ------------------------------------------------

    /** The cached recipient set and security mode, or null before the first sync. */
    fun projectCrypto(): ProjectCrypto? =
        queries.getProjectCrypto().executeAsOneOrNull()?.let { row ->
            ProjectCrypto(
                securityMode = row.security_mode,
                projectKeys = Json.decodeFromString<List<StoredProjectKey>>(row.project_keys_json)
                    .map { it.toProjectKey() },
            )
        }

    fun putProjectCrypto(crypto: ProjectCrypto) = queries.putProjectCrypto(
        crypto.securityMode,
        Json.encodeToString(crypto.projectKeys.map(StoredProjectKey::from)),
        now().toString(),
    )

    fun contentKeyFor(submissionId: String): ContentKey? =
        queries.contentKeyForSubmission(submissionId).executeAsOneOrNull()?.let {
            ContentKey(it.content_key_id, it.submission_id, it.key_material, it.uploaded == 1L)
        }

    /**
     * Stores a content key and its wraps together. One transaction because a
     * key without its wraps is data nobody can ever decrypt — including us,
     * once the material is gone.
     */
    fun putContentKey(key: ContentKey, wraps: List<WrappedKeyRecord>): ContentKey =
        queries.transactionWithResult {
            queries.insertContentKey(
                key.contentKeyId, key.submissionId, key.material, now().toString(),
            )
            for (wrap in wraps) {
                queries.insertWrappedKey(
                    key.contentKeyId, wrap.projectKeyId, wrap.ephemeralPublic,
                    wrap.nonce, wrap.wrappedKey,
                )
            }
            key
        }

    /**
     * Keeps the ciphertext an op was encrypted to, so a retry sends the same
     * bytes rather than encrypting again.
     *
     * Re-deriving would be correct in principle — the nonce comes from
     * `(deviceId, counter)`, not from a random source, so the result is
     * identical — but AES-GCM implementations refuse to encrypt twice under the
     * same `(key, nonce)` and are right to: doing it by accident, with
     * different plaintext, is the failure the whole scheme guards against.
     * Storing the result means the question never arises.
     */
    fun recordOpCiphertext(
        opId: String,
        ciphertext: String,
        contentKeyId: String,
        nonce: String,
    ) = queries.recordOpCiphertext(ciphertext, contentKeyId, nonce, opId)

    fun wrapsFor(contentKeyId: String): List<WrappedKeyRecord> =
        queries.wrapsForContentKey(contentKeyId).executeAsList().map {
            WrappedKeyRecord(it.project_key_id, it.ephemeral_public, it.nonce, it.wrapped_key)
        }

    /**
     * Marks a content key as landed. Called only once the server has accepted an
     * op encrypted under it: an accepted op proves the key it references was
     * stored, since the server rejects `unknown_content_key` otherwise.
     */
    fun markContentKeyUploaded(contentKeyId: String) =
        queries.markContentKeyUploaded(contentKeyId)

    // -- device registration ----------------------------------------------

    fun isDeviceRegistered(): Boolean =
        queries.getDeviceState().executeAsOne().registered == 1L

    fun markDeviceRegistered() = queries.markDeviceRegistered()

    /**
     * Writes one pulled batch and advances the cursor in the SAME transaction,
     * so the cursor is persisted only once the batch is durable (sync §5).
     * Replays are no-ops via INSERT OR IGNORE on opId.
     */
    fun applyPullBatch(ops: List<SyncOp>, nextCursor: Long) = queries.transaction {
        for (op in ops) {
            queries.insertSubmissionIfAbsent(
                op.submissionId, op.formId, op.formVersion.toLong(), op.wallClock, op.wallClock,
            )
            queries.insertRemoteOp(
                op.opId, op.submissionId, op.formId, op.formVersion.toLong(), op.kind,
                op.path, op.valueJson, op.valueCiphertext, op.contentKeyId, op.nonce,
                op.deviceId, op.actorId, op.counter, op.wallClock,
            )
        }
        queries.setPullCursor(nextCursor)
    }

    fun syncStatus(): SyncStatus = queries.getSyncStatus().executeAsOne().let {
        SyncStatus(it.pull_cursor, it.last_sync_at, it.last_error)
    }

    fun observeSyncStatus(
        context: CoroutineContext = Dispatchers.Default,
    ): Flow<SyncStatus> =
        queries.getSyncStatus().asFlow().mapToList(context).map { rows ->
            rows.firstOrNull()?.let { SyncStatus(it.pull_cursor, it.last_sync_at, it.last_error) }
                ?: SyncStatus(0, null, null)
        }

    fun recordSyncSuccess() = queries.recordSyncSuccess(now().toString())

    fun recordSyncError(message: String) = queries.recordSyncError(message)

    /**
     * Folds a submission's op log into its current answers, last writer wins by
     * `(counter, deviceId)` — the query returns ops already in that order.
     */
    fun materialisedAnswers(submissionId: String): Map<String, FormValue> {
        val values = LinkedHashMap<String, FormValue>()
        for (op in opsFor(submissionId)) {
            val path = op.path ?: continue
            when (op.kind) {
                OpKind.SET -> when {
                    // Our own op: the plaintext is here even when the outgoing
                    // ciphertext is cached beside it.
                    op.valueJson != null ->
                        values[path] = formValueFromJson(Json.parseToJsonElement(op.valueJson))
                    // Another device's encrypted answer, and this device holds
                    // no private key. Dropping the path says "no readable value
                    // here"; folding it as Null would claim the field was
                    // answered blank, which is a different and false statement
                    // about someone's data.
                    op.isEncrypted -> values.remove(path)
                    else -> values[path] = FormValue.Null
                }
                OpKind.UNSET -> values.remove(path)
            }
        }
        return values
    }

    fun getSubmission(submissionId: String): SubmissionSummary? =
        queries.getSubmission(submissionId).executeAsOneOrNull()?.let {
            SubmissionSummary(
                submissionId = it.submission_id,
                formId = it.form_id,
                formVersion = it.form_version.toInt(),
                status = it.status,
                createdAt = it.created_at,
                updatedAt = it.updated_at,
                pendingOps = it.pending_ops,
            )
        }

    fun observeSubmissions(
        context: CoroutineContext = Dispatchers.Default,
    ): Flow<List<SubmissionSummary>> =
        queries.listSubmissions().asFlow().mapToList(context).map { rows ->
            rows.map {
                SubmissionSummary(
                    submissionId = it.submission_id,
                    formId = it.form_id,
                    formVersion = it.form_version.toInt(),
                    status = it.status,
                    createdAt = it.created_at,
                    updatedAt = it.updated_at,
                    pendingOps = it.pending_ops,
                )
            }
        }
}
