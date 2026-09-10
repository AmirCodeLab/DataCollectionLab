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
     * Everything this device is waiting for, across every form version the
     * server still deploys to it, with the cost of fetching each.
     *
     * Deployed versions only: a withdrawn version is kept so its drafts open
     * (Form IR §9), and spending a village connection on reference data for a
     * questionnaire nobody is collecting any more is exactly the wrong trade.
     */
    fun pendingFetches(): List<PendingFetch> =
        forms.all()
            .filter { it.deployed }
            .flatMap { datasets.pinnedLists(it.formVersionId) }
            .filterNot { it.complete }
            .distinctBy { it.datasetVersionId }
            .sortedBy { it.datasetKey }
            .map { list ->
                PendingFetch(
                    list = list,
                    deltaBaseVersion = datasets
                        .deltaBaseFor(list.datasetKey, list.datasetVersionId)
                        ?.let { base -> datasets.find(base)?.version },
                    estimatedFullBytes = estimateFullBytes(list),
                )
            }

    /**
     * Bytes per row, measured off whatever this device holds of the same list,
     * times the row count the manifest declared. Null when the device holds no
     * row of that list at all and would be inventing the number.
     */
    private fun estimateFullBytes(list: PinnedList): Long? {
        val rowCount = list.rowCount ?: return null
        val sample = datasets.all()
            .filter { it.datasetKey == list.datasetKey }
            .map { it.datasetVersionId }
            .firstOrNull { datasets.rowsHeld(it) > 0 }
            ?: return null
        val rows = datasets.rowsHeld(sample)
        if (rows == 0L) return null
        return datasets.bytesHeld(sample) * rowCount / rows
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

/**
 * One list this device is waiting for, with what fetching it would cost.
 *
 * The cost is the point (item 4 §3.2). "Update from v7" and "full download,
 * about 11 MB" are different decisions on a village connection, and a person
 * has to be able to make that decision **before** tapping, not by watching a
 * progress bar and regretting it.
 */
data class PendingFetch(
    val list: PinnedList,
    /** A complete earlier version of the same list to diff against, or null. */
    val deltaBaseVersion: Int?,
    /**
     * Bytes a full transfer would take, estimated from rows this device
     * already holds of the same list, or null when it holds none and cannot
     * honestly say. A row count is still shown in that case.
     */
    val estimatedFullBytes: Long?,
) {
    val statusLine: String get() = list.statusLine

    /**
     * What it will cost, in the words that decide it.
     *
     * A delta carries no size, and that is not an oversight: the server does
     * not know what changed until it computes the diff, and the whole point of
     * a delta is not to enumerate the list first. So the honest line names the
     * base it will diff against and the size of the alternative, which is the
     * comparison the person is actually making.
     */
    val costLine: String
        get() {
            val full = estimatedFullBytes?.let { "about ${formatBytes(it)}" }
                ?: list.rowCount?.let { "${group(it)} rows" }
                ?: "size unknown"
            return if (deltaBaseVersion != null) {
                "Update from v$deltaBaseVersion — only the rows that changed. " +
                    "The whole list is $full."
            } else {
                "Full download — $full."
            }
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

/** 11_300_000 -> "11.3 MB". One decimal: the choice is coarse, and so is this. */
fun formatBytes(bytes: Long): String {
    val kb = bytes / 1024.0
    if (kb < 1024) return "${kb.toLong()} KB"
    val tenths = (kb / 1024.0 * 10).toLong()
    return "${tenths / 10}.${tenths % 10} MB"
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
