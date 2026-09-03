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
 * ## The current shape, and what part 5 changes
 *
 * Rows are read out of SQLCipher and filtered in memory. That is honest for
 * now and is *not* the performance contract being met: §3.2 promises resolution
 * proportional to the rows matching the selector, and this reads the whole
 * version to find them. The interface is what makes the difference addressable
 * — an index on the selector columns is a change to this class and to nothing
 * else, and the engine, the vectors and every client stay exactly as they are.
 * Measuring it on the Pixel at 38,000 rows is what decides whether it has to
 * happen before the item is done (item 4 part 5).
 */
class StoredDatasetSource(
    private val store: DatasetStore,
    private val formVersionId: String,
) : DatasetSource {

    private val rowSerializer = MapSerializer(String.serializer(), String.serializer())
    private val json = Json { ignoreUnknownKeys = true }

    /** Parsed once per dataset key per instance; a form re-resolves constantly. */
    private val cache = mutableMapOf<String, List<Map<String, FormValue>>>()

    override fun rows(
        dataset: String,
        selector: Map<String, FormValue>,
        equals: Pair<String, FormValue>?,
    ): List<Map<String, FormValue>> {
        val all = cache.getOrPut(dataset) {
            store.rowsFor(formVersionId, dataset).map { (_, dataJson) ->
                json.decodeFromString(rowSerializer, dataJson)
                    .mapValues { (_, cell) -> FormValue.Text(cell) as FormValue }
            }
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
}
