package com.dcp.core.sync

import app.cash.sqldelight.db.SqlDriver
import com.dcp.core.db.DcpDatabase
import kotlin.time.Clock
import kotlin.time.ExperimentalTime
import kotlin.time.Instant

/** One dataset version held on this device, as the server described it. */
data class StoredDatasetVersion(
    val datasetVersionId: String,
    val datasetKey: String,
    val version: Int,
    val checksum: String,
    /** What the manifest said it holds — not what has arrived. */
    val rowCount: Int,
    /** False until every page has arrived. A partial list is not the list. */
    val complete: Boolean,
    /** Where to resume from, or null when there is nothing to resume. */
    val nextCursor: String?,
    /** The columns a form filters on, as the server named them (§3.2). */
    val filterColumns: List<String>,
    val fetchedAt: String,
)

/** One entry of the server's dataset manifest (`GET /sync/pull?scope=datasets`). */
data class DatasetManifestEntry(
    val formVersionId: String,
    val datasetKey: String,
    val datasetVersionId: String,
    val version: Int,
    val rowCount: Int,
    val checksum: String,
    /**
     * The columns this form's filters narrow on — what to index (§3.2).
     *
     * The server names them because the server is what knows: the filter is in
     * the IR. A device indexing every column instead was measured on a Pixel 6
     * Pro at eight columns times 38,000 villages — 304,000 entries, a 7x slower
     * first sync and a **105x slower delta**, because a delta copies the index
     * across to the new version.
     */
    val filterColumns: List<String> = emptyList(),
)

/** A dataset a form version needs and this device does not have whole. */
data class MissingDataset(val datasetKey: String, val datasetVersionId: String)

/**
 * The reference data this device holds, and the one way to read it.
 *
 * ## What this class is really for
 *
 * `FormStore` is about retention. This is about **refusing to be stale**, which
 * is a different job and a harder one, because staleness here has no symptom.
 *
 * The failure it is built against: the device holds v1 of `villages`, the
 * server has moved to v2, and an enumerator picks a village that no longer
 * exists. Every screen looks normal. The form opens, the list scrolls, the
 * search works, the answer saves and syncs. Nothing anywhere is in an error
 * state, and the data is wrong. A delta mechanism makes it *more* likely rather
 * than less, because "nothing changed" and "I failed to ask" produce the same
 * silence.
 *
 * So the resolver takes a **form version**, never a dataset key alone:
 *
 * ```
 * rowsFor(formVersionId, "villages")   // the only way to read rows
 * ```
 *
 * There is no `rowsFor("villages")` and no overload that takes a version id,
 * because the answer to "the rows for villages" would have to be "whichever
 * version happens to be here". That is the same mistake as validating a v1
 * answer against v2's choice list (breaks 30, 40, 42) with a village list
 * instead of a choice list, and it is fixed the same way: the caller is not
 * given the choice. The server said which version this form version was
 * published against; that statement is stored; and a request for anything else
 * comes back empty.
 *
 * Empty, and not wrong. An empty select is visible to an enumerator and to
 * [missingFor], which is what turns "the reference data has not arrived" into a
 * sentence somebody reads rather than a list they mistrust.
 *
 * This class is Kotlin-only and no conformance vector can reach it (docs/project-conventions.md,
 * "Where the conformance architecture stops protecting you" — deciding *which*
 * list is used is precisely the kind of decision a vector cannot see).
 * `DatasetStoreTest` is what watches it.
 */
@OptIn(ExperimentalTime::class)
class DatasetStore(
    db: DcpDatabase,
    private val driver: SqlDriver? = null,
    private val now: () -> Instant = { Clock.System.now() },
) {
    private val queries = db.datasetsQueries

    /** Every dataset version held, whole or part-transferred. */
    fun all(): List<StoredDatasetVersion> =
        queries.heldDatasetVersions(::toStored).executeAsList()

    fun find(datasetVersionId: String): StoredDatasetVersion? =
        queries.datasetVersion(datasetVersionId, ::toStored).executeAsOneOrNull()

    /**
     * Which of [manifest] this device does not already hold, whole.
     *
     * Compared on the server's checksum, and on completeness. A version whose
     * transfer stopped half way is *missing*, not held: it is present in the
     * table, it has a plausible number of rows, and it is not the list.
     *
     * Reads no rows off disk. On this table that is not a nicety — comparing by
     * content would mean loading 38,000 rows on every sync to discover that
     * nothing had changed.
     */
    fun missingFrom(manifest: List<DatasetManifestEntry>): List<DatasetManifestEntry> {
        val held = queries.heldDatasetChecksums().executeAsList()
            .associateBy { it.dataset_version_id }
        return manifest
            .distinctBy { it.datasetVersionId }
            .filter { entry ->
                val row = held[entry.datasetVersionId]
                row == null || row.checksum != entry.checksum || row.complete != 1L
            }
    }

    /**
     * Record the manifest: what each form version was published against, and a
     * placeholder for any version whose rows have not arrived.
     *
     * The pins are replaced per form version rather than merged, because the
     * manifest is a complete statement about that form version. A pin left
     * behind from an earlier manifest would be a list this device believes a
     * form uses and the server does not, which is the stale failure wearing a
     * different hat.
     *
     * One transaction: a device that died half way through would otherwise come
     * back holding rows nothing pins to, and forms pinned to rows it never
     * fetched.
     */
    fun applyManifest(manifest: List<DatasetManifestEntry>) = queries.transaction {
        val fetchedAt = now().toString()
        manifest.map { it.formVersionId }.distinct().forEach(queries::replaceFormVersionPins)
        manifest.forEach { entry ->
            queries.insertFormVersionPin(
                form_version_id = entry.formVersionId,
                dataset_key = entry.datasetKey,
                dataset_version_id = entry.datasetVersionId,
            )
            val held = queries.datasetVersion(entry.datasetVersionId, ::toStored)
                .executeAsOneOrNull()
            // A version already held whole and matching is left exactly as it
            // is — re-writing the row would reset `complete` and cost a device
            // a 38,000-row re-fetch for a manifest that said nothing new.
            if (held == null || held.checksum != entry.checksum) {
                queries.deleteRows(entry.datasetVersionId)
                queries.deleteCells(entry.datasetVersionId)
                queries.upsertDatasetVersion(
                    dataset_version_id = entry.datasetVersionId,
                    dataset_key = entry.datasetKey,
                    version = entry.version.toLong(),
                    checksum = entry.checksum,
                    row_count = entry.rowCount.toLong(),
                    complete = 0L,
                    next_cursor = null,
                    filter_columns = entry.filterColumns.joinToString(","),
                    fetched_at = fetchedAt,
                )
            }
        }
    }

    /**
     * Store one page of rows and remember where to resume.
     *
     * [nextCursor] null means this was the last page, and only then is the
     * version marked complete — the point at which it becomes readable at all.
     * A device that stops mid-transfer resumes from the cursor rather than
     * starting again, which on a 38,000-row list over a field connection is the
     * difference between finishing and not.
     */
    fun appendRows(
        datasetVersionId: String,
        rows: List<Pair<String, String>>,
        nextCursor: String?,
    ) = queries.transaction {
        rows.forEach { (key, json) ->
            queries.insertRow(
                dataset_version_id = datasetVersionId,
                record_key = key,
                data_json = json,
            )
            index(datasetVersionId, key, json)
        }
        if (nextCursor == null) {
            queries.markComplete(datasetVersionId)
        } else {
            queries.setCursor(next_cursor = nextCursor, dataset_version_id = datasetVersionId)
        }
    }

    /**
     * Seed a new version from one this device already holds, then apply a diff.
     *
     * The rows are copied inside the database — one statement, no network —
     * because what a delta saves is the *transfer*. Copied rather than renamed:
     * another form version this device holds may still pin the old one, and an
     * enumerator with a v2 draft the morning v3 lands is exactly that case.
     * Retention decides when the old version goes, not this.
     *
     * [nextCursor] null marks the new version complete, on the same rule as a
     * full transfer: until the last page arrives, a half-applied diff is not
     * the list, and the store will not serve it.
     */
    fun applyDelta(
        datasetVersionId: String,
        fromDatasetVersionId: String,
        changed: List<Pair<String, String>>,
        deleted: List<String>,
        nextCursor: String?,
        seed: Boolean,
    ) = queries.transaction {
        if (seed) {
            queries.copyRowsToVersion(
                dataset_version_id = datasetVersionId,
                dataset_version_id_ = fromDatasetVersionId,
            )
            // The index travels with the rows. Rebuilding it would mean parsing
            // every row the delta did not touch, which is the cost the delta
            // exists to avoid.
            queries.copyCellsToVersion(
                dataset_version_id = datasetVersionId,
                dataset_version_id_ = fromDatasetVersionId,
            )
        }
        changed.forEach { (key, json) ->
            queries.insertRow(
                dataset_version_id = datasetVersionId,
                record_key = key,
                data_json = json,
            )
            // The old cells first: a changed row keeps its key, so an entry for
            // a value it no longer has would leave it matching a filter it
            // should have dropped out of.
            queries.deleteCellsForRow(datasetVersionId, key)
            index(datasetVersionId, key, json)
        }
        deleted.forEach {
            queries.deleteRow(datasetVersionId, it)
            queries.deleteCellsForRow(datasetVersionId, it)
        }
        if (nextCursor == null) {
            queries.markComplete(datasetVersionId)
        } else {
            queries.setCursor(next_cursor = nextCursor, dataset_version_id = datasetVersionId)
        }
    }

    /**
     * A complete version of the same dataset this device could diff from, or null.
     *
     * Only a **complete** one: diffing from a half-transferred list would apply
     * a correct patch to an incorrect base and mark the result whole, which is
     * a wrong village list that every check agrees about. The newest is chosen
     * because it is the least different.
     */
    fun deltaBaseFor(datasetKey: String, exclude: String): String? =
        queries.heldDatasetVersions(::toStored).executeAsList()
            .filter { it.datasetKey == datasetKey && it.complete && it.datasetVersionId != exclude }
            .maxByOrNull { it.version }
            ?.datasetVersionId

    /**
     * The rows a form version's `dataset_key` resolves to — the only reader.
     *
     * Empty when the pinned version is not held, or is not yet whole. Both are
     * the honest answer and both are visible: [missingFor] is what turns either
     * into a sentence, and an empty select on screen is a problem somebody
     * reports rather than a wrong village somebody chooses.
     */
    fun rowsFor(formVersionId: String, datasetKey: String): List<Pair<String, String>> =
        queries.rowsForFormVersion(formVersionId, datasetKey) { key, json -> key to json }
            .executeAsList()

    /**
     * The rows a form version's list narrows to, **by index** (§3.2).
     *
     * The query the performance contract is about. One and two selector columns
     * become a primary-key lookup on `dataset_cell`, so only matching rows are
     * read and parsed. Anything wider returns null and the caller scans —
     * correct, slow, and *stated* rather than hidden.
     *
     * Two is not an arbitrary stopping point: it is every cascade there is.
     * Region to district to village narrows on one column at each step, and the
     * UCL plot list on two.
     */
    fun rowsMatching(
        formVersionId: String,
        datasetKey: String,
        selector: List<Pair<String, String>>,
    ): List<Pair<String, String>>? {
        // Only when the index actually covers every column being asked about.
        //
        // An index that does not cover a column answers "no rows" rather than
        // "I cannot help", so taking this path regardless would resolve a filter
        // on an unindexed column to an **empty village list**, on a device
        // holding every village, with nothing in an error state. That is the
        // stale-list failure by a different road, and a test caught it the first
        // time `filter_columns` became selective.
        val indexed = queries.indexedColumnsForFormVersion(formVersionId, datasetKey)
            .executeAsOneOrNull()
            ?.split(",")
            ?.filter { it.isNotEmpty() }
            ?.toSet()
            .orEmpty()
        if (!indexed.containsAll(selector.map { it.first })) return null
        return rowsMatchingIndexed(formVersionId, datasetKey, selector)
    }

    private fun rowsMatchingIndexed(
        formVersionId: String,
        datasetKey: String,
        selector: List<Pair<String, String>>,
    ): List<Pair<String, String>>? = when (selector.size) {
        1 -> queries.rowsForFormVersionWhere1(
            formVersionId, datasetKey, selector[0].first, selector[0].second,
        ) { key, json -> key to json }.executeAsList()
        2 -> queries.rowsForFormVersionWhere2(
            formVersionId, datasetKey,
            selector[0].first, selector[0].second,
            selector[1].first, selector[1].second,
        ) { key, json -> key to json }.executeAsList()
        else -> null
    }

    /**
     * One entry per non-empty cell, so a selector is a lookup rather than a scan.
     *
     * Parsed with a deliberately small reader rather than a JSON library: this
     * runs once per row on a first sync — 38,000 times for the UCL village list
     * — and dataset rows are flat text-to-text by construction (§3.2).
     */
    private fun index(datasetVersionId: String, key: String, json: String) {
        val wanted = indexedColumns(datasetVersionId)
        if (wanted.isEmpty()) return
        flatJsonPairs(json).forEach { (column, value) ->
            if (value.isNotEmpty() && column in wanted) {
                queries.insertCell(
                    dataset_version_id = datasetVersionId,
                    column_name = column,
                    cell_value = value,
                    record_key = key,
                )
            }
        }
    }

    /**
     * The datasets this form version needs and this device cannot serve.
     *
     * Asked before a form is offered, so that "the village list has not arrived
     * yet" is something an enumerator is told at the start rather than
     * something they infer from an empty dropdown in the middle.
     */
    fun missingFor(formVersionId: String): List<MissingDataset> =
        queries.missingDatasetsForFormVersion(formVersionId) { key, id -> MissingDataset(key, id) }
            .executeAsList()

    /** What the server said this form version was published against. */
    fun pinsFor(formVersionId: String): Map<String, String> =
        queries.pinsForFormVersion(formVersionId) { key, id -> key to id }
            .executeAsList()
            .toMap()

    /**
     * Drop reference data no form version this device holds still pins to.
     *
     * Retention is `FormStore`'s rule one level down and follows it rather than
     * restating it: whatever form versions survive pruning, their lists survive
     * with them. Nothing here asks whether the server still deploys a dataset,
     * because that is already answered transitively — a withdrawn form version
     * is pruned by `FormStore`, and its pins go with it.
     *
     * Which is why the pins are swept first. A pin whose form version is gone
     * would otherwise keep a 38,000-row list alive forever, on the strength of
     * a form nobody can open.
     */
    fun prune(): Int = queries.transactionWithResult {
        queries.orphanedPins().executeAsList().forEach(queries::replaceFormVersionPins)
        val removable = queries.deletableDatasetVersions().executeAsList()
        removable.forEach { id ->
            queries.deleteRows(id)
            queries.deleteCells(id)
            queries.deleteDatasetVersion(id)
        }
        removable.size
    }

    /**
     * Which columns this version indexes, read once per transaction.
     *
     * Cached because `index` runs once per row — 38,000 times on a first sync —
     * and a query per row would cost more than the indexing does.
     */
    private val indexedColumnsCache = mutableMapOf<String, Set<String>>()

    private fun indexedColumns(datasetVersionId: String): Set<String> =
        indexedColumnsCache.getOrPut(datasetVersionId) {
            queries.datasetVersion(datasetVersionId, ::toStored)
                .executeAsOneOrNull()
                ?.filterColumns
                ?.toSet()
                .orEmpty()
        }

    private fun toStored(
        datasetVersionId: String,
        datasetKey: String,
        version: Long,
        checksum: String,
        rowCount: Long,
        complete: Long,
        nextCursor: String?,
        filterColumns: String,
        fetchedAt: String,
    ) = StoredDatasetVersion(
        datasetVersionId = datasetVersionId,
        datasetKey = datasetKey,
        version = version.toInt(),
        checksum = checksum,
        rowCount = rowCount.toInt(),
        complete = complete == 1L,
        nextCursor = nextCursor,
        filterColumns = filterColumns.split(",").filter { it.isNotEmpty() },
        fetchedAt = fetchedAt,
    )
}


/**
 * The pairs of a flat `{"a":"b"}` document, without a JSON parser.
 *
 * Runs once per row on a first sync — 38,000 times for the UCL village list —
 * and a general parser spends most of that allocating. Dataset rows are flat
 * text-to-text by construction (Form IR §3.2): a CSV holds nothing else, and
 * the server serialises them as such.
 *
 * Anything not of that shape yields nothing, so an unexpected document costs an
 * unindexed row rather than an exception during a sync. The row is still stored
 * and still readable through the scan path.
 */
internal fun flatJsonPairs(json: String): List<Pair<String, String>> {
    val out = mutableListOf<Pair<String, String>>()
    var index = 0

    fun readString(): String? {
        while (index < json.length && json[index] != '"') {
            if (json[index] == '}') return null
            index++
        }
        if (index >= json.length) return null
        index++
        val text = StringBuilder()
        while (index < json.length) {
            val c = json[index]
            if (c == '"') {
                index++
                return text.toString()
            }
            if (c == BACKSLASH) {
                index++
                if (index >= json.length) return null
                when (val escaped = json[index]) {
                    'n' -> text.append('\n')
                    't' -> text.append('\t')
                    'r' -> text.append('\r')
                    'u' -> {
                        if (index + 4 >= json.length) return null
                        val code = json.substring(index + 1, index + 5).toIntOrNull(16)
                            ?: return null
                        text.append(code.toChar())
                        index += 4
                    }
                    else -> text.append(escaped)
                }
                index++
            } else {
                text.append(c)
                index++
            }
        }
        return null
    }

    while (index < json.length) {
        val key = readString() ?: break
        while (index < json.length && json[index] != ':' && json[index] != '}') index++
        if (index >= json.length || json[index] == '}') break
        index++
        while (index < json.length && json[index] == ' ') index++
        // Only a string value is indexable. A number or an object is skipped and
        // the row stays readable through the scan path.
        if (index < json.length && json[index] != '"') continue
        val value = readString() ?: break
        out += key to value
    }
    return out
}

private const val BACKSLASH = '\\'
