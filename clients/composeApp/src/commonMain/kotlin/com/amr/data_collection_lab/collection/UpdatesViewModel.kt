package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dcp.core.sync.FormStore
import com.dcp.core.sync.PendingFetch
import com.dcp.core.sync.ReferenceData
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.SyncClient
import com.dcp.core.sync.SyncScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** A deployed form version this device has not downloaded. */
data class FormUpdateUi(val title: String, val version: Int)

/**
 * A list this device is waiting for, and what fetching it would cost.
 *
 * [costLine] is the reason this screen exists. "Update from v7" and "full
 * download, about 11.3 MB" are different decisions on a village connection,
 * and a person has to be able to make that one before tapping rather than by
 * watching a progress bar and regretting it.
 */
data class ListUpdateUi(
    val datasetKey: String,
    val statusLine: String,
    val costLine: String,
    /** Some of it is already here, so the button says Resume. */
    val partial: Boolean,
)

@Stable
data class UpdatesState(
    val isLoading: Boolean = true,
    val forms: List<FormUpdateUi> = emptyList(),
    val lists: List<ListUpdateUi> = emptyList(),
    /** When each scope was last checked, or that it never has been. */
    val formsStatus: String = "",
    val listsStatus: String = "",
    /** "forms", or a dataset key, while that fetch is running. */
    val busy: String? = null,
    val outcome: String? = null,
    val error: String? = null,
)

sealed interface UpdatesAction {
    data object OnUpdateForms : UpdatesAction
    data class OnUpdateList(val datasetKey: String) : UpdatesAction
}

/**
 * The two explicit updates (item 4): form documents, and reference data.
 *
 * Neither is reachable from the primary sync, and that is the whole design.
 * The work sync carries the answers and both manifests, so by the time this
 * screen is opened the device already knows what it is missing and what it
 * would cost — offline, from local state, without spending a byte to find out.
 */
class UpdatesViewModel(
    private val store: SubmissionStore,
    private val forms: FormStore,
    private val referenceData: ReferenceData,
    private val syncClient: SyncClient,
) : ViewModel() {

    private val _state = MutableStateFlow(UpdatesState())
    val state = _state.asStateFlow()

    init {
        refresh()
    }

    fun onAction(action: UpdatesAction) {
        when (action) {
            UpdatesAction.OnUpdateForms -> run("forms") {
                val result = syncClient.updateForms()
                when {
                    result.error != null -> _state.update { it.copy(error = result.error) }
                    result.fetched == 0 -> _state.update {
                        it.copy(outcome = "Already up to date.", error = null)
                    }
                    else -> _state.update {
                        it.copy(outcome = formsOutcome(result.fetched, result.nowNeeded), error = null)
                    }
                }
            }
            is UpdatesAction.OnUpdateList -> run(action.datasetKey) {
                val result = syncClient.updateReferenceData(action.datasetKey)
                if (result.error != null) {
                    _state.update { it.copy(error = result.error) }
                } else {
                    _state.update {
                        it.copy(outcome = "${action.datasetKey}: ${result.fetched} rows.", error = null)
                    }
                }
            }
        }
    }

    /**
     * What a form update changed, and what it now needs.
     *
     * The second half is the point: the moment after a form lands is the only
     * moment a person is still deciding what to spend a connection on, and
     * saying it costs nothing because the dataset manifest rode along with the
     * same request. Without it, the gap is discovered in a village, offline,
     * at the roster.
     */
    private fun formsOutcome(fetched: Int, needed: List<PendingFetch>): String {
        val downloaded = if (fetched == 1) "1 form downloaded." else "$fetched forms downloaded."
        if (needed.isEmpty()) return "$downloaded Everything they need is on this device."
        return "$downloaded They need " + needed.joinToString(", ") { it.statusLine } +
            ". Interviews can be started now; they cannot be finalised until it arrives."
    }

    private fun run(busy: String, block: suspend () -> Unit) {
        if (_state.value.busy != null) return
        viewModelScope.launch {
            _state.update { it.copy(busy = busy, outcome = null, error = null) }
            try {
                withContext(Dispatchers.Default) { block() }
            } finally {
                _state.update { it.copy(busy = null) }
                refresh()
            }
        }
    }

    private fun refresh() {
        viewModelScope.launch {
            val snapshot = withContext(Dispatchers.Default) {
                val statuses = store.scopeStatuses().associateBy { it.scope }
                Triple(
                    forms.deployedNotHeld().map { FormUpdateUi(it.title, it.version) },
                    referenceData.pendingFetches().map {
                        ListUpdateUi(
                            datasetKey = it.list.datasetKey,
                            statusLine = it.statusLine,
                            costLine = it.costLine,
                            partial = it.list.rowsHeld > 0,
                        )
                    },
                    statuses,
                )
            }
            val (formList, lists, statuses) = snapshot
            _state.update {
                it.copy(
                    isLoading = false,
                    forms = formList,
                    lists = lists,
                    formsStatus = scopeLine(statuses[SyncScope.FORMS]?.lastOkAt),
                    listsStatus = scopeLine(statuses[SyncScope.DATASETS]?.lastOkAt),
                )
            }
        }
    }

    /**
     * The time half of a scope's status, and only the time half.
     *
     * What the device HOLDS is on each row above, as rows of a total. A
     * timestamp on its own is the sentence that lies — "updated 3 minutes ago"
     * over 12,400 of 38,000 rows — so it is never the whole line.
     */
    private fun scopeLine(lastOkAt: String?): String =
        lastOkAt?.let { "Checked ${it.take(16).replace("T", " ")}" } ?: "Not checked yet"
}
