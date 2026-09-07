package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import com.dcp.core.sync.OpKind
import com.dcp.core.sync.SyncOp
import com.dcp.form.CompileException
import com.dcp.form.FormInstance
import com.dcp.form.FormNavigator

/**
 * The roster: the view over Form IR §11.3, and nothing more than a view.
 *
 * Every rule here belongs to the engine and is only read: which rows exist and
 * in what order (`FormInstance.instances`), what a row is called
 * (`summaryLabel`), whether adding and deleting are permitted (`addInstance`
 * and `deleteInstance` refuse, and §2.3 decides), what the two pairs inside an
 * instance read (`FormNavigator.instanceProgress`). A client that decided any
 * of these itself would be the second implementation §6.2 warns about, and no
 * vector reaches a client.
 *
 * Pure functions, so they can be tested without a Compose runtime or a main
 * dispatcher; [CollectionViewModel] is the thin thing that calls them.
 */

/** One row of the roster, as the list shows it. */
@Stable
data class RowUi(
    val instanceId: String,
    /** §2.3's chain: summaryLabel, else the source row's label, else the position. */
    val label: String,
    /** Whether §2.3 lets this row be deleted. */
    val canDelete: Boolean,
)

/** A repeat screen (§11.3): the rows, and the controls §2.3 permits. */
@Stable
data class RosterUi(
    val repeatId: String,
    val title: String,
    val rows: List<RowUi>,
    val canAdd: Boolean,
    /** The form's own wording for the add control, or null for the client's. */
    val addLabel: String?,
)

/** Where the enumerator is inside a row (§11.3's two pairs). */
@Stable
data class InstanceUi(
    val repeatId: String,
    val instanceId: String,
    val rowLabel: String,
    /** 1-based screen within the row, of how many are relevant. */
    val withinPosition: Int,
    val withinTotal: Int,
    /** 1-based row within the roster, of how many rows exist. */
    val acrossPosition: Int,
    val acrossTotal: Int,
)

/** `members[i3].age` → `age`; a top-level path is its own field id. */
fun fieldIdOf(path: String): String =
    if (path.contains("].")) path.substringAfterLast("].") else path

/** `members[i3].age` → `members` to `i3`, or null for a top-level path. */
fun scopeOfPath(path: String): Pair<String, String>? {
    val open = path.indexOf('[')
    val close = path.indexOf(']')
    if (open < 0 || close < open) return null
    return path.substring(0, open) to path.substring(open + 1, close)
}

/** The path a question inside the open instance is answered under. */
fun instancePath(repeatId: String, instanceId: String, fieldId: String): String =
    "$repeatId[$instanceId].$fieldId"

/**
 * The roster for the current screen, or null when the current screen is not
 * a repeat screen or the enumerator is inside a row.
 *
 * Add and delete are asked of the engine by the only honest means it offers:
 * whether the operation would be refused. The engine's [FormInstance.addInstance]
 * throws on a `countExpr` repeat, a row source without `allowAdd`, and a full
 * roster; the same three facts are read here without mutating anything, by
 * reproducing §2.3's rule from the node — and `RosterTest` holds the two side
 * by side so they cannot drift.
 */
fun rosterUi(navigator: FormNavigator, instance: FormInstance, language: String): RosterUi? {
    if (navigator.position.inside) return null
    val screen = navigator.currentScreen ?: return null
    val repeatId = screen.repeatId ?: return null
    val node = instance.form.repeats[repeatId] ?: return null
    val order = instance.instances[repeatId].orEmpty()
    val source = node.rowSource
    val deletable = node.countExpr == null &&
        (source == null || source.allowDelete) &&
        // §2.3: a floor only where the enumerator supplies the rows.
        (source != null || order.size > (node.minInstances ?: 0))
    val addable = node.countExpr == null &&
        (source == null || source.allowAdd) &&
        (node.maxInstances?.let { order.size < it } ?: true)
    return RosterUi(
        repeatId = repeatId,
        title = node.label.resolve(language) ?: repeatId,
        rows = order.map { id ->
            RowUi(
                instanceId = id,
                label = instance.summaryLabel(repeatId, id, language),
                canDelete = deletable,
            )
        },
        canAdd = addable,
        addLabel = instance.renderedAddLabel(repeatId, language),
    )
}

/** The open row's two pairs, or null outside one. */
fun instanceUi(navigator: FormNavigator, instance: FormInstance, language: String): InstanceUi? {
    val position = navigator.position
    if (!position.inside) return null
    val repeatId = navigator.currentScreen?.repeatId ?: return null
    val instanceId = position.instanceId ?: return null
    val (within, across) = navigator.instanceProgress() ?: return null
    return InstanceUi(
        repeatId = repeatId,
        instanceId = instanceId,
        rowLabel = instance.summaryLabel(repeatId, instanceId, language),
        withinPosition = within.first,
        withinTotal = within.second,
        acrossPosition = across.first,
        acrossTotal = across.second,
    )
}

/**
 * Rebuilds the rows an op log describes, before the answers are set.
 *
 * `repeat_add` and `repeat_delete` (sync §2) are replayed in log order against
 * the engine, which mints instance ids from its own counter — `i1`, `i2` — so
 * a replay in the order the ids were minted reproduces them. That is asserted,
 * not assumed: an id that comes back different from the one the log recorded
 * means the answers keyed on it would land on the wrong row, and this throws
 * rather than let that happen silently (defect 14's shape, one layer down).
 *
 * Rows a fixed list or a countExpr seeds are the engine's already and are not
 * in the log. Only the enumerator's adds and deletes are.
 */
fun replayInstanceOps(instance: FormInstance, ops: List<SyncOp>) {
    for (op in ops) {
        val path = op.path ?: continue
        when (op.kind) {
            OpKind.REPEAT_ADD -> {
                val (repeatId, recorded) = scopeOfPath(path) ?: continue
                val minted = instance.addInstance(repeatId)
                if (minted != recorded) {
                    throw CompileException(
                        "replaying $path minted '$minted' — the answers recorded under " +
                            "'$recorded' cannot be placed"
                    )
                }
            }
            OpKind.REPEAT_DELETE -> {
                val (repeatId, recorded) = scopeOfPath(path) ?: continue
                val index = instance.instances[repeatId]?.indexOf(recorded) ?: -1
                if (index >= 0) instance.deleteInstance(repeatId, index)
            }
        }
    }
}
