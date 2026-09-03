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
                queries.upsertDatasetVersion(
                    dataset_version_id = entry.datasetVersionId,
                    dataset_key = entry.datasetKey,
                    version = entry.version.toLong(),
                    checksum = entry.checksum,
                    row_count = entry.rowCount.toLong(),
                    complete = 0L,
                    next_cursor = null,
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
        }
        if (nextCursor == null) {
            queries.markComplete(datasetVersionId)
        } else {
            queries.setCursor(next_cursor = nextCursor, dataset_version_id = datasetVersionId)
        }
    }

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
            queries.deleteDatasetVersion(id)
        }
        removable.size
    }

    private fun toStored(
        datasetVersionId: String,
        datasetKey: String,
        version: Long,
        checksum: String,
        rowCount: Long,
        complete: Long,
        nextCursor: String?,
        fetchedAt: String,
    ) = StoredDatasetVersion(
        datasetVersionId = datasetVersionId,
        datasetKey = datasetKey,
        version = version.toInt(),
        checksum = checksum,
        rowCount = rowCount.toInt(),
        complete = complete == 1L,
        nextCursor = nextCursor,
        fetchedAt = fetchedAt,
    )
}
