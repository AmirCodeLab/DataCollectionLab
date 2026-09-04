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

/**
 * One form version held on this device, as it came from the server.
 *
 * [irJson] is the document verbatim rather than something parsed: compiling it
 * is the client's business and the bytes are what [irChecksum] addresses.
 */
data class StoredFormVersion(
    val formVersionId: String,
    val formId: String,
    val version: Int,
    val title: String,
    val irJson: String,
    val irChecksum: String,
    /** False once the server's manifest stopped listing it — see [applyManifest]. */
    val deployed: Boolean,
    val fetchedAt: String,
)

/** One entry of the server's manifest (`GET /sync/pull?scope=forms`). */
data class FormManifestEntry(
    val formVersionId: String,
    val formId: String,
    val version: Int,
    val title: String,
    val irChecksum: String,
)

/**
 * The form versions this device holds.
 *
 * Before this existed a form reached a phone only by being compiled into the
 * app, which meant a customer's own form could not be collected on a real
 * device at all. The server now says which versions this device's environment
 * runs and the device keeps them here.
 *
 * ## What this class is really for
 *
 * Not caching — retention. Form IR §9 validates a submission against the
 * version it was collected under, so the rule is not "hold the current form",
 * it is **hold every version anything on this device still refers to**. An
 * enumerator can be part-way through a v2 interview on the morning v3 deploys,
 * and a device that dropped v2 would have a draft it could no longer open: the
 * op log records the answers, not the questions.
 *
 * So a version leaves this store only when both halves are true — the server
 * has stopped deploying it, and no submission here was collected under it.
 * Either half alone is wrong in a way that shows up in the field and not in a
 * demo. See [prune].
 *
 * This class is Kotlin-only and no conformance vector can reach it (docs/project-conventions.md,
 * "Where the conformance architecture stops protecting you"). `FormStoreTest`
 * is what watches it.
 */
@OptIn(ExperimentalTime::class)
class FormStore(
    db: DcpDatabase,
    private val now: () -> Instant = { Clock.System.now() },
) {
    private val queries = db.formsQueries

    /** Every version held, deployed or not. A draft against a withdrawn version still opens. */
    fun all(): List<StoredFormVersion> = queries.allFormVersions(::toStored).executeAsList()

    /**
     * [all], as a flow that re-emits when the table changes.
     *
     * A screen that reports which forms a device holds has to follow the store
     * rather than read it once, because the moment it is wrong is the moment
     * that matters: a sync has just delivered a form and the screen still says
     * there is none. That is not a stale list, it is the screen contradicting
     * the thing it was opened to explain — and it was found exactly that way,
     * on a device, with the form sitting in the database underneath it.
     */
    fun observeAll(context: CoroutineContext = Dispatchers.Default): Flow<List<StoredFormVersion>> =
        queries.allFormVersions().asFlow().mapToList(context).map { rows ->
            rows.map {
                toStored(
                    it.form_version_id, it.form_id, it.version, it.title,
                    it.ir_json, it.ir_checksum, it.deployed, it.fetched_at,
                )
            }
        }

    /**
     * What a new submission may be started on: still deployed, highest version
     * of each form.
     *
     * Superseded versions are deliberately absent. They must remain *openable*
     * (that is [find]), and starting fresh data collection on a version the
     * server has moved past would produce submissions nobody asked for.
     */
    fun startable(): List<StoredFormVersion> =
        queries.startableFormVersions(::toStored).executeAsList()

    /** The exact version a submission was collected under (Form IR §9). */
    fun find(formId: String, version: Int): StoredFormVersion? =
        queries.formVersion(formId, version.toLong(), ::toStored).executeAsOneOrNull()

    /**
     * Which of [manifest] this device does not already hold, byte for byte.
     *
     * Compared on the server's content checksum, not on (formId, version): a
     * version whose content changed under the same number must not pass for the
     * document already on the phone. Reads no IR off disk — only ids and
     * checksums — because this runs on every sync and the documents are the
     * expensive part.
     */
    fun missingFrom(manifest: List<FormManifestEntry>): List<FormManifestEntry> {
        val held = queries.heldFormVersionChecksums().executeAsList()
            .associate { it.form_version_id to it.ir_checksum }
        return manifest.filter { held[it.formVersionId] != it.irChecksum }
    }

    /**
     * Record the server's manifest, and the documents fetched for it.
     *
     * The manifest is a complete statement of what this device's environment
     * deploys, not a delta — that is what lets a device notice a version being
     * **withdrawn**, which no stream of additions could tell it. So everything
     * is marked undeployed first and the manifest re-marks what it lists.
     *
     * [documents] is keyed by `formVersionId` and carries only the versions
     * [missingFrom] said were needed. A manifest entry with no document is
     * still applied: the device keeps the version it already had and simply
     * confirms it is still deployed.
     *
     * One transaction. A device that died half way through this would otherwise
     * come back with every form marked undeployed and nothing to re-mark them.
     */
    fun applyManifest(
        manifest: List<FormManifestEntry>,
        documents: Map<String, String>,
    ) = queries.transaction {
        queries.markAllUndeployed()
        val fetchedAt = now().toString()
        manifest.forEach { entry ->
            val document = documents[entry.formVersionId]
            if (document == null) {
                queries.markDeployed(entry.formVersionId)
            } else {
                queries.upsertFormVersion(
                    form_version_id = entry.formVersionId,
                    form_id = entry.formId,
                    version = entry.version.toLong(),
                    title = entry.title,
                    ir_json = document,
                    ir_checksum = entry.irChecksum,
                    fetched_at = fetchedAt,
                )
            }
        }
    }

    /**
     * Drop versions nothing needs any more, and report how many went.
     *
     * Both conditions, always: withdrawn by the server **and** unreferenced by
     * any submission on this device. Pruning on the first alone destroys the
     * form behind a draft an enumerator is holding; pruning on the second alone
     * never prunes at all, since a deployed version is by definition still
     * wanted.
     *
     * Kept separate from [applyManifest] rather than folded into it so that a
     * sync which fetched forms successfully cannot also delete one as a side
     * effect of a manifest that arrived truncated.
     */
    fun prune(): Int = queries.transactionWithResult {
        val removable = queries.deletableFormVersions().executeAsList()
        removable.forEach { queries.deleteFormVersion(it) }
        removable.size
    }

    private fun toStored(
        formVersionId: String,
        formId: String,
        version: Long,
        title: String,
        irJson: String,
        irChecksum: String,
        deployed: Long,
        fetchedAt: String,
    ) = StoredFormVersion(
        formVersionId = formVersionId,
        formId = formId,
        version = version.toInt(),
        title = title,
        irJson = irJson,
        irChecksum = irChecksum,
        deployed = deployed == 1L,
        fetchedAt = fetchedAt,
    )
}
