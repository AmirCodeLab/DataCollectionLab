package com.dcp.core.sync

import app.cash.sqldelight.coroutines.asFlow
import app.cash.sqldelight.coroutines.mapToList
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
)

data class SubmissionSummary(
    val submissionId: String,
    val formId: String,
    val formVersion: Int,
    val status: String,
    val createdAt: String,
    val updatedAt: String,
    val pendingOps: Long,
)

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
) {
    private val queries = db.syncQueries
    val deviceId: String

    init {
        val candidate = "dev_" + buildString {
            repeat(8) { append("0123456789abcdef"[Random.nextInt(16)]) }
        }
        queries.initDeviceState(candidate) // INSERT OR IGNORE: first launch only
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

    fun opsFor(submissionId: String): List<SyncOp> =
        queries.opsForSubmission(submissionId).executeAsList().map {
            SyncOp(
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
                synced = it.synced != 0L,
            )
        }

    /**
     * Folds a submission's op log into its current answers, last writer wins by
     * `(counter, deviceId)` — the query returns ops already in that order.
     */
    fun materialisedAnswers(submissionId: String): Map<String, FormValue> {
        val values = LinkedHashMap<String, FormValue>()
        for (op in opsFor(submissionId)) {
            val path = op.path ?: continue
            when (op.kind) {
                OpKind.SET -> values[path] =
                    op.valueJson?.let { formValueFromJson(Json.parseToJsonElement(it)) }
                        ?: FormValue.Null
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
