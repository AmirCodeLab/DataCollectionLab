package com.amr.data_collection_lab.collection

import com.dcp.core.sync.HeldCase
import com.dcp.form.FormValue

/**
 * What the submission list makes of the cases this device holds (item 2).
 *
 * Plain functions, so the decisions the screen rests on are testable without
 * a ViewModel: which cases are offered to start work on, which released
 * cases are still shown because there is work on them, and what a tap on a
 * case does. The rule underneath all three is §4.3 of the analysis — a
 * release never costs a draft, and never hides one.
 */

/** A case as the list shows it. */
data class CaseUi(
    val caseId: String,
    /** The composite key — "S3|1|1" — or the id when the sample has none. */
    val label: String,
    /** A line from the sample row: the first few values that are not the key. */
    val summary: String,
    val assigned: Boolean,
    /** Submissions on this device against the case. */
    val submissions: Long,
    /** The most recently touched of them, which a tap opens. */
    val latestSubmissionId: String?,
)

data class CaseSections(
    /** Held now, ordered as the statement orders them. */
    val assigned: List<CaseUi>,
    /**
     * Released by a later statement but with work on this device. Listed so
     * the draft is reachable and named; a released case with no work is not
     * shown — there is nothing on the device about it.
     */
    val releasedWithWork: List<CaseUi>,
)

/** What a tap on a case does. */
sealed interface CaseTap {
    /** Work on it already: open the newest draft. */
    data class OpenExisting(val submissionId: String) : CaseTap

    /** Nothing on it yet: start a submission bound to the case. */
    data class StartNew(val caseId: String) : CaseTap

    /**
     * Not this person's any more and nothing started: refused here, before
     * the server would refuse the first op as `not_assigned`. A draft is
     * never refused — that is the `OpenExisting` branch.
     */
    data class Refused(val message: String) : CaseTap
}

fun HeldCase.toUi(): CaseUi = CaseUi(
    caseId = caseId,
    label = caseKey ?: caseId,
    summary = data.entries
        .filter { (k, v) -> k != "case_key" && v.isNotBlank() }
        .take(3)
        .joinToString(" · ") { (k, v) -> "$k: $v" },
    assigned = assigned,
    submissions = submissions,
    latestSubmissionId = latestSubmissionId,
)

fun sectionsOf(cases: List<HeldCase>): CaseSections = CaseSections(
    assigned = cases.filter { it.assigned }.map { it.toUi() },
    releasedWithWork = cases.filter { !it.assigned && it.submissions > 0 }.map { it.toUi() },
)

fun tapOn(case: CaseUi): CaseTap = when {
    case.latestSubmissionId != null -> CaseTap.OpenExisting(case.latestSubmissionId)
    case.assigned -> CaseTap.StartNew(case.caseId)
    else -> CaseTap.Refused(
        "Case ${case.label} is no longer assigned to you. Ask your supervisor to " +
            "assign it to you, then sync.",
    )
}

/** `_metadata.case_key` for the engine (Form IR §2.3), or nothing for uncased work. */
fun caseMetadata(caseKey: String?): Map<String, FormValue> =
    if (caseKey == null) emptyMap() else mapOf("case_key" to FormValue.Text(caseKey))

/** The line under the form's title in the collection screen. */
fun caseNoteFor(caseKey: String?, assigned: Boolean?): String? = when {
    caseKey == null -> null
    assigned == false -> "Case $caseKey · no longer assigned to you — the draft is kept"
    else -> "Case $caseKey"
}
