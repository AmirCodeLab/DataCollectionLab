package com.dcp.core.sync

import com.dcp.form.DatasetSource
import com.dcp.form.FormValue
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * The engine's [DatasetSource], served from what this device holds.
 *
 * Form IR §3.2 draws a line and this class is on the near side of it: **a
 * source decides how quickly rows are found, never which rows exist.** The
 * engine has already decomposed the filter into a selector and a residual; all
 * that is asked here is "the rows matching these column values", and answering
 * anything else — a guess, a subset, a fallback — would make this class the
 * thing that decides what a question offers, which is exactly the decision a
 * conformance vector cannot see.
 *
 * ## Why it is bound to one form version
 *
 * The constructor takes a `formVersionId` and there is no way to read rows
 * without one. That is [DatasetStore]'s rule carried up: the dataset key in the
 * IR (`"dataset": "villages"`) is a key, not a version, and the version it
 * means is whatever the *server said this form version was published against*.
 * A source that resolved a key against "whatever is in the database" would
 * serve last month's villages to this month's form and nothing anywhere would
 * be in an error state.
 *
 * So a stale or half-transferred list resolves to **no rows**, which an
 * enumerator sees as an empty list — visible, reportable, and wrong in the
 * direction that gets noticed.
 *
 * ## Two paths, and the measurement that produced the second one
 *
 * The first cut read the whole version out of SQLCipher and filtered it in
 * memory. On a Pixel 6 Pro with 38,000 villages that cost **1,589 ms on the
 * first keystroke** and held 46 MB of heap — the app stopping for a second and
 * a half when an enumerator taps the village question. §3.2 promised resolution
 * proportional to the rows matching the selector, and that was proportional to
 * the dataset.
 *
 * So the columns are indexed on the way in and a selector of one or two columns
 * — which is every cascade there is — becomes a lookup. Only matching rows are
 * read and parsed.
 *
 * The in-memory path survives for wider selectors, and [scanned] says when it
 * was used. A fallback nobody can see is a performance contract nobody can
 * check: the difference between the two is three orders of magnitude, and it
 * must not be something a form author discovers in a village.
 */
class StoredDatasetSource(
    private val store: DatasetStore,
    private val formVersionId: String,
) : DatasetSource {

    private val rowSerializer = MapSerializer(String.serializer(), String.serializer())
    private val json = Json { ignoreUnknownKeys = true }

    /** Parsed once per dataset key per instance, for the scan path only. */
    private val cache = mutableMapOf<String, List<Map<String, FormValue>>>()

    /**
     * Rows read whole because narrowing was not available, and whether that
     * ever happened *with a selector in hand*.
     *
     * A boolean was the first cut and it was useless the first time it ran on a
     * device: the region question has no filter, so reading all 26 regions set
     * the flag, and the report then said the village list had scanned 37,852
     * rows when it had done an index lookup. A number that cannot tell 26 from
     * 37,852 is not measuring the thing it was added for.
     *
     * The two are separate on purpose. An unfiltered list is not a fallback —
     * there is nothing to narrow, and reading it is the answer to the question.
     * [narrowingUnavailable] is the alarming one: a selector existed and the
     * index could not serve it, which is the case §3.2's contract is about.
     */
    var scannedRows: Long = 0
        private set

    /** A selector was present and could not be served by the index (§3.2). */
    var narrowingUnavailable: Boolean = false
        private set

    override fun rows(
        dataset: String,
        selector: Map<String, FormValue>,
        equals: Pair<String, FormValue>?,
    ): List<Map<String, FormValue>> {
        // The indexed path. A selector term whose value is not text cannot be a
        // lookup — the index stores cells, and a CSV holds nothing but text —
        // and a null one matches nothing at all, which §3.2 makes the correct
        // answer rather than a reason to widen.
        val terms = buildList {
            selector.forEach { (column, value) -> add(column to value) }
            if (equals != null) add(equals)
        }
        if (terms.isNotEmpty() && terms.all { it.second is FormValue.Text }) {
            val lookup = terms.map { it.first to (it.second as FormValue.Text).value }
            store.rowsMatching(formVersionId, dataset, lookup)?.let { found ->
                return found.map { (_, dataJson) -> parse(dataJson) }
            }
        }
        if (terms.any { it.second is FormValue.Null }) return emptyList()

        // The scan. Correct, slow, and recorded — separately for the two
        // reasons it happens, because only one of them is a problem.
        if (terms.isNotEmpty()) narrowingUnavailable = true
        val all = cache.getOrPut(dataset) {
            val read = store.rowsFor(formVersionId, dataset)
            scannedRows += read.size.toLong()
            read.map { (_, dataJson) -> parse(dataJson) }
        }
        // The same comparison the reference source makes — exact, §3.1 and
        // §6.3's rule — so a device and the server agree about membership.
        var matched = all.filter { row ->
            selector.all { com.dcp.form.InMemoryDatasetSource.same(row[it.key], it.value) }
        }
        if (equals != null) {
            matched = matched.filter {
                com.dcp.form.InMemoryDatasetSource.same(it[equals.first], equals.second)
            }
        }
        return matched
    }

    private fun parse(dataJson: String): Map<String, FormValue> =
        json.decodeFromString(rowSerializer, dataJson)
            .mapValues { (_, cell) -> FormValue.Text(cell) as FormValue }
}
