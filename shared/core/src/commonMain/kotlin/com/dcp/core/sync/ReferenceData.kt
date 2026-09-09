package com.dcp.core.sync

/**
 * Whether this device holds the reference data a form version was published
 * against — asked in **one** place (item 4, D2).
 *
 * There is no device-wide "in sync" flag and there must not be one. A form
 * version is ready when every dataset version it pins is held and complete;
 * the pins are the representation of a partial state, and they are already
 * local (`form_version_dataset` joined to `dataset_version.complete`).
 *
 * ## Why this is a class and not two queries
 *
 * Two surfaces ask this question: the finalisation gate, which refuses to
 * call an interview complete when the device could not put its questions, and
 * the updates screen, which says what is missing and what it would cost. If
 * they computed it separately the screen could say ready while the gate
 * refused, or the reverse — the shape known defect 24 had, two surfaces
 * answering one question from two places. So `DatasetStore.missingFor` is read
 * from here and nowhere else, and `ReferenceDataOneAnswerTest` fails the build
 * if a second caller appears.
 *
 * The sentences live here too, beside each other, so the refusal and the
 * status line cannot drift apart in wording either.
 */
class ReferenceData(
    private val forms: FormStore,
    private val datasets: DatasetStore,
    private val submissions: SubmissionStore,
) {
    /** Readiness of one form version, by its server id. */
    fun readinessOf(formVersionId: String): Readiness {
        val waiting = datasets.pinnedLists(formVersionId).filterNot { it.complete }
        return if (waiting.isEmpty()) Readiness.Ready else Readiness.Waiting(waiting)
    }

    /**
     * Readiness of the version a submission was collected under — never the
     * newest the device holds (Form IR §9, break 30's rule).
     *
     * A submission whose version this device does not hold answers **ready**,
     * deliberately. That state is retention having failed, the collection
     * screen already names it, and answering "waiting for reference data"
     * would put the wrong sentence in front of the enumerator.
     */
    fun readinessOfSubmission(submissionId: String): Readiness {
        val summary = submissions.getSubmission(submissionId) ?: return Readiness.Ready
        val version = forms.find(summary.formId, summary.formVersion) ?: return Readiness.Ready
        return readinessOf(version.formVersionId)
    }
}

/** What the updates screen shows: content, with the time elsewhere. */
val PinnedList.statusLine: String
    get() = when {
        rowsHeld == 0L -> "$label — not downloaded"
        else -> "$label — ${group(rowsHeld)} of ${group(rowCount)} rows"
    }

/** The same fact, phrased for the middle of a refusal. */
internal val PinnedList.shortfall: String
    get() = when {
        rowsHeld == 0L -> "$label not downloaded"
        else -> "$label has ${group(rowsHeld)} of ${group(rowCount)} rows"
    }

/** `villages v8`, or `villages` when no manifest has said which version. */
private val PinnedList.label: String
    get() = if (version == null) datasetKey else "$datasetKey v$version"

sealed interface Readiness {
    val isReady: Boolean

    /** The lists still wanted; empty when ready. */
    val lists: List<PinnedList>

    data object Ready : Readiness {
        override val isReady = true
        override val lists = emptyList<PinnedList>()
    }

    data class Waiting(override val lists: List<PinnedList>) : Readiness {
        override val isReady = false
    }

    /** One line per list, for a screen. */
    fun statusLines(): List<String> = lists.map { it.statusLine }

    /**
     * What a person reads when finalisation is refused, or null when it is
     * not. It names the list and the action, because "cannot finalise" alone
     * is not usable in a village.
     */
    fun refusal(): String? =
        if (lists.isEmpty()) null else "Cannot finalise: ${shortfalls()} — tap Reference data."

    /**
     * The middle of that sentence, on its own, so a translation supplies only
     * the frame and never re-derives the facts. English lives in [refusal] and
     * nowhere else; Arabic lives in `I18n` and nowhere else.
     */
    fun shortfalls(): String = lists.joinToString(", ") { it.shortfall }
}

/** 38000 -> "38,000". Grouped by hand: commonMain has no locale formatter. */
private fun group(value: Int?): String = if (value == null) "?" else group(value.toLong())

private fun group(value: Long): String {
    val digits = value.toString()
    val out = StringBuilder()
    digits.forEachIndexed { index, ch ->
        if (index > 0 && (digits.length - index) % 3 == 0) out.append(',')
        out.append(ch)
    }
    return out.toString()
}
