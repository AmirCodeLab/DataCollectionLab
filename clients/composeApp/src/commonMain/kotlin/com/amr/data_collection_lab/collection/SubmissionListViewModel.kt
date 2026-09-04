package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dcp.core.sync.SubmissionStatus
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.SyncClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class SubmissionUi(
    val submissionId: String,
    val formTitle: String,
    /**
     * Shown beside the title. Two submissions on the same form can be on
     * different versions — a draft started before a deployment and one started
     * after — and they are not the same questionnaire.
     */
    val formVersion: Int,
    val savedAt: String,
    val finalized: Boolean,
    val pendingOps: Long,
)

@Stable
data class SubmissionListState(
    val submissions: List<SubmissionUi> = emptyList(),
    /**
     * Forms this device may start a new submission on — delivered by the server
     * (sync §5), not bundled. Empty means the device has synced no forms yet,
     * which is a different situation from having no submissions and has to be
     * said differently: one is "get started", the other is "there is nothing to
     * get started on".
     */
    val startableForms: List<FormChoice> = emptyList(),
    /** True while the form picker is up, for a device holding more than one. */
    val isChoosingForm: Boolean = false,
    val isLoading: Boolean = true,
    val pendingTotal: Long = 0,
    val lastSyncAt: String? = null,
    val lastSyncError: String? = null,
    /** e.g. "3 ops rejected: not_authorized" — the server refused these ops. */
    val rejectedSummary: String? = null,
    /**
     * Why the last sync could not refresh this device's forms. Separate from
     * [lastSyncError] because it did not fail the sync: the answers moved, and
     * the device still holds the forms it had.
     */
    val formError: String? = null,
    /**
     * The server refused to register this device (e.g. `project_not_found`).
     * Held apart from [lastSyncError] because nothing will sync until someone
     * fixes the server — retrying cannot help.
     */
    val registrationFailure: String? = null,
    val isSyncing: Boolean = false,
)

sealed interface SubmissionListAction {
    data object OnNewSubmissionClick : SubmissionListAction
    data object OnSyncClick : SubmissionListAction
    data class OnSubmissionClick(val submissionId: String) : SubmissionListAction
    /** A form chosen from the picker; starts a submission on that version. */
    data class OnFormChosen(val form: FormChoice) : SubmissionListAction
    data object OnFormChoiceDismissed : SubmissionListAction
}

sealed interface SubmissionListEvent {
    data class NavigateToCollection(val submissionId: String) : SubmissionListEvent
}

class SubmissionListViewModel(
    private val store: SubmissionStore,
    private val catalog: FormCatalog,
    private val syncClient: SyncClient,
) : ViewModel() {

    private val _state = MutableStateFlow(SubmissionListState())
    val state = _state.asStateFlow()

    private val _events = Channel<SubmissionListEvent>()
    val events = _events.receiveAsFlow()

    init {
        viewModelScope.launch {
            refreshStartableForms()
            store.observeSubmissions().collect { rows ->
                // One title lookup per distinct version on screen, not per row:
                // a device holding three versions of one form renders rows for
                // all three, and each says which it belongs to.
                val titles = rows.map { it.formId to it.formVersion }.distinct()
                    .associateWith { (formId, version) -> catalog.titleFor(formId, version) }
                _state.update { s ->
                    s.copy(
                        isLoading = false,
                        pendingTotal = rows.sumOf { it.pendingOps },
                        submissions = rows.map {
                            SubmissionUi(
                                submissionId = it.submissionId,
                                formTitle = titles[it.formId to it.formVersion] ?: it.formId,
                                formVersion = it.formVersion,
                                savedAt = it.updatedAt.take(16).replace("T", " "),
                                finalized = it.status == SubmissionStatus.FINALIZED,
                                pendingOps = it.pendingOps,
                            )
                        },
                    )
                }
            }
        }
        viewModelScope.launch {
            store.observeSyncStatus().collect { status ->
                _state.update {
                    it.copy(
                        lastSyncAt = status.lastSyncAt?.take(16)?.replace("T", " "),
                        lastSyncError = status.lastError,
                    )
                }
            }
        }
        viewModelScope.launch {
            store.observeRejectedOpSummary().collect { groups ->
                _state.update { s ->
                    s.copy(
                        rejectedSummary = groups
                            .takeIf { it.isNotEmpty() }
                            ?.joinToString("; ") { "${it.count} ops rejected: ${it.reason}" },
                    )
                }
            }
        }
    }

    fun onAction(action: SubmissionListAction) {
        when (action) {
            is SubmissionListAction.OnNewSubmissionClick -> viewModelScope.launch {
                // Re-read rather than trusting the cached list: a sync may have
                // delivered or withdrawn a form since this screen opened.
                val forms = refreshStartableForms()
                when (forms.size) {
                    // Nothing to start. The button stays enabled and says so,
                    // because "sync to get your forms" is the actual next step
                    // and a disabled button explains nothing.
                    0 -> Unit
                    1 -> startSubmission(forms.single())
                    else -> _state.update { it.copy(isChoosingForm = true) }
                }
            }
            is SubmissionListAction.OnFormChosen -> viewModelScope.launch {
                _state.update { it.copy(isChoosingForm = false) }
                startSubmission(action.form)
            }
            SubmissionListAction.OnFormChoiceDismissed ->
                _state.update { it.copy(isChoosingForm = false) }
            is SubmissionListAction.OnSyncClick -> sync()
            is SubmissionListAction.OnSubmissionClick -> viewModelScope.launch {
                _events.send(SubmissionListEvent.NavigateToCollection(action.submissionId))
            }
        }
    }

    private fun sync() {
        if (_state.value.isSyncing) return
        viewModelScope.launch {
            _state.update { it.copy(isSyncing = true) }
            try {
                // The error text lands in sync_status and is observed above;
                // only the registration verdict needs carrying by hand.
                val result = withContext(Dispatchers.Default) { syncClient.syncOnce() }
                _state.update {
                    it.copy(
                        registrationFailure = result.registrationFailure,
                        formError = result.formError,
                    )
                }
                // A sync is how forms arrive, so the picker's list is stale the
                // moment one finishes.
                refreshStartableForms()
            } finally {
                _state.update { it.copy(isSyncing = false) }
            }
        }
    }

    private suspend fun startSubmission(form: FormChoice) {
        val id = store.createDraft(form.formId, form.version)
        _events.send(SubmissionListEvent.NavigateToCollection(id))
    }

    private suspend fun refreshStartableForms(): List<FormChoice> =
        catalog.startable().also { forms ->
            _state.update { it.copy(startableForms = forms) }
        }
}
