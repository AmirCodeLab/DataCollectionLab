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
    val savedAt: String,
    val finalized: Boolean,
    val pendingOps: Long,
)

@Stable
data class SubmissionListState(
    val submissions: List<SubmissionUi> = emptyList(),
    val isLoading: Boolean = true,
    val pendingTotal: Long = 0,
    val lastSyncAt: String? = null,
    val lastSyncError: String? = null,
    /** e.g. "3 ops rejected: not_authorized" — the server refused these ops. */
    val rejectedSummary: String? = null,
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
            val form = catalog.compiledForm()
            val title = form.ir.title.resolve(form.ir.defaultLanguage ?: "en") ?: form.formId
            store.observeSubmissions().collect { rows ->
                _state.update { s ->
                    s.copy(
                        isLoading = false,
                        pendingTotal = rows.sumOf { it.pendingOps },
                        submissions = rows.map {
                            SubmissionUi(
                                submissionId = it.submissionId,
                                formTitle = title,
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
                val form = catalog.compiledForm()
                val id = store.createDraft(form.formId, form.version)
                _events.send(SubmissionListEvent.NavigateToCollection(id))
            }
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
                _state.update { it.copy(registrationFailure = result.registrationFailure) }
            } finally {
                _state.update { it.copy(isSyncing = false) }
            }
        }
    }
}
