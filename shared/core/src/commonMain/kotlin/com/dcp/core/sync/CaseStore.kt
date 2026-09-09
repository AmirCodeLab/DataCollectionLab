package com.dcp.core.sync

import app.cash.sqldelight.coroutines.asFlow
import app.cash.sqldelight.coroutines.mapToList
import com.dcp.core.db.DcpDatabase
import kotlin.coroutines.CoroutineContext
import kotlin.time.Clock
import kotlin.time.ExperimentalTime
import kotlin.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** One entry of the assignment statement a device pulls (sync §5). */
data class AssignedCase(
    val caseId: String,
    val caseKey: String?,
    val datasetKey: String?,
    val status: String,
    val priority: Long,
    val dueAt: String?,
    /** The sample row behind the case, as JSON text. */
    val dataJson: String,
)

/** A case as this device holds it, whether or not it is still assigned. */
data class HeldCase(
    val caseId: String,
    val caseKey: String?,
    val datasetKey: String?,
    val status: String,
    val priority: Long,
    val dueAt: String?,
    val dataJson: String,
    /** Listed by the latest statement. False once a statement omitted it. */
    val assigned: Boolean,
    val firstSeenAt: String,
    val releasedSeenAt: String?,
    /** Submissions on this device against the case. */
    val submissions: Long,
    val latestSubmissionId: String?,
) {
    /** The sample row's values, as strings, in the order the server sent them. */
    val data: Map<String, String>
        get() = runCatching {
            (Json.parseToJsonElement(dataJson) as? JsonObject)?.entries
                ?.associate { (k, v) -> k to ((v as? JsonPrimitive)?.content ?: v.toString()) }
        }.getOrNull() ?: emptyMap()
}

/**
 * The cases assigned to this device's person (item 2, analysis §6.2).
 *
 * The statement the server sends with `scope=assignments` is complete: every
 * case the person holds, every time. So [applyStatement] is the whole
 * protocol — what is in the statement is assigned, what was here and is not
 * has been released. A release is recorded and never deleted: a draft on a
 * released case is still this enumerator's work, still finishable and still
 * pushable, and the row is what lets the list say which case it was for.
 *
 * There is no delete in this class and none in the schema behind it.
 */
@OptIn(ExperimentalTime::class)
class CaseStore(
    db: DcpDatabase,
    private val now: () -> Instant = { Clock.System.now() },
) {
    private val queries = db.syncQueries

    /**
     * Brings the local rows in line with one complete statement, in one
     * transaction: everything is marked released, then each listed case is
     * written back as assigned. A case that was released and is listed again
     * — reassigned back — comes back as assigned with its release cleared.
     */
    fun applyStatement(statement: List<AssignedCase>) = queries.transaction {
        val at = now().toString()
        queries.markAllCasesReleased(at)
        for (case in statement) {
            queries.insertCaseIfAbsent(
                case.caseId, case.caseKey, case.datasetKey, case.dataJson, case.status,
                case.priority, case.dueAt, at,
            )
            queries.markCaseAssigned(
                case.caseKey, case.datasetKey, case.dataJson, case.status, case.priority,
                case.dueAt, case.caseId,
            )
        }
    }

    fun get(caseId: String): HeldCase? =
        list().firstOrNull { it.caseId == caseId }

    /** The case key for `_metadata.case_key`, or null for uncased work. */
    fun caseKeyFor(caseId: String): String? =
        queries.getCase(caseId).executeAsOneOrNull()?.case_key

    fun list(): List<HeldCase> = queries.listCases().executeAsList().map { it.toHeld() }

    fun observe(context: CoroutineContext = Dispatchers.Default): Flow<List<HeldCase>> =
        queries.listCases().asFlow().mapToList(context).map { rows -> rows.map { it.toHeld() } }

    private fun com.dcp.core.db.ListCases.toHeld() = HeldCase(
        caseId = case_id,
        caseKey = case_key,
        datasetKey = dataset_key,
        status = status,
        priority = priority,
        dueAt = due_at,
        dataJson = data_json,
        assigned = assigned == 1L,
        firstSeenAt = first_seen_at,
        releasedSeenAt = released_seen_at,
        submissions = submissions,
        latestSubmissionId = queries.latestSubmissionForCase(case_id).executeAsOneOrNull(),
    )
}

/**
 * What the server's push refusals mean to the person holding the phone.
 *
 * A reason is the server's contract (`RejectReason` on the API); the text is
 * what the sync bar shows beside it, and it has to say what to DO. The one
 * item 2 adds, `not_assigned`, is the one where the wrong wording costs
 * data: the draft is kept, and the person must hear that.
 */
object RejectReasons {
    const val NOT_ASSIGNED = "not_assigned"

    fun describe(reason: String, count: Long): String = when (reason) {
        NOT_ASSIGNED ->
            "$count ${ops(count)} refused: the case is no longer assigned to you. " +
                "The draft is kept on this device; it will sync once your supervisor " +
                "assigns the case back to you."
        "unknown_form_version" ->
            "$count ${ops(count)} waiting: the form version is not published on the server yet."
        "submission_closed" ->
            "$count ${ops(count)} refused: the submission was closed on the server."
        "not_authorized" ->
            "$count ${ops(count)} refused: this device is not authorised for the project."
        else -> "$count ${ops(count)} rejected: $reason"
    }

    private fun ops(count: Long) = if (count == 1L) "op" else "ops"
}
