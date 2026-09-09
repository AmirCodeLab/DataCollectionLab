package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dcp.core.sync.CaseStore
import com.dcp.core.sync.RejectReasons
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
    /** The case this work is against — "S3|1|1" — or null for uncased work. */
    val caseKey: String? = null,
    /**
     * False when the case has moved to someone else since the draft was
     * opened: shown as "no longer assigned to you", and nothing else changes —
     * the draft is kept, finishable and pushable (item 2, analysis §4.3).
     */
    val caseAssigned: Boolean? = null,
)

@Stable
data class SubmissionListState(
    val submissions: List<SubmissionUi> = emptyList(),
    /** The cases assigned to this person, as the last sync's statement said. */
    val assignedCases: List<CaseUi> = emptyList(),
    /** Cases released since, with work on this device — still reachable. */
    val releasedCases: List<CaseUi> = emptyList(),
    /**
     * Why a tap on a case did nothing: it is no longer this person's and no
     * work had started. Cleared by the next action.
     */
    val caseRefusal: String? = null,
    /** The case a new submission is being started against, while the form
     *  picker is up; null for uncased work. */
    val startingForCase: String? = null,
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
    /** A case tapped: opens its draft, starts one, or says why not. */
    data class OnCaseClick(val caseId: String) : SubmissionListAction
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
    private val cases: CaseStore,
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
                                caseKey = it.caseKey,
                                caseAssigned = it.caseAssigned,
                            )
                        },
                    )
                }
            }
        }
        viewModelScope.launch {
            cases.observe().collect { held ->
                val sections = sectionsOf(held)
                _state.update {
                    it.copy(assignedCases = sections.assigned, releasedCases = sections.releasedWithWork)
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
                            ?.joinToString("; ") { RejectReasons.describe(it.reason, it.count) },
                    )
                }
            }
        }
    }

    fun onAction(action: SubmissionListAction) {
        when (action) {
            is SubmissionListAction.OnNewSubmissionClick -> viewModelScope.launch {
                _state.update { it.copy(caseRefusal = null) }
                startWork(caseId = null)
            }
            is SubmissionListAction.OnCaseClick -> viewModelScope.launch {
                val case = (_state.value.assignedCases + _state.value.releasedCases)
                    .firstOrNull { it.caseId == action.caseId } ?: return@launch
                when (val tap = tapOn(case)) {
                    is CaseTap.OpenExisting -> {
                        _state.update { it.copy(caseRefusal = null) }
                        _events.send(SubmissionListEvent.NavigateToCollection(tap.submissionId))
                    }
                    is CaseTap.StartNew -> {
                        _state.update { it.copy(caseRefusal = null) }
                        startWork(caseId = tap.caseId)
                    }
                    is CaseTap.Refused -> _state.update { it.copy(caseRefusal = tap.message) }
                }
            }
            is SubmissionListAction.OnFormChosen -> viewModelScope.launch {
                val forCase = _state.value.startingForCase
                _state.update { it.copy(isChoosingForm = false, startingForCase = null) }
                startSubmission(action.form, forCase)
            }
            SubmissionListAction.OnFormChoiceDismissed ->
                _state.update { it.copy(isChoosingForm = false, startingForCase = null) }
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

    /**
     * Starts work, against [caseId] when it came from the case list. Re-reads
     * the forms rather than trusting the cached list: a sync may have
     * delivered or withdrawn a form since this screen opened.
     */
    private suspend fun startWork(caseId: String?) {
        val forms = refreshStartableForms()
        when (forms.size) {
            // Nothing to start. The button stays enabled and says so, because
            // "sync to get your forms" is the actual next step and a disabled
            // button explains nothing.
            0 -> Unit
            1 -> startSubmission(forms.single(), caseId)
            else -> _state.update { it.copy(isChoosingForm = true, startingForCase = caseId) }
        }
    }

    private suspend fun startSubmission(form: FormChoice, caseId: String?) {
        val id = store.createDraft(form.formId, form.version, caseId)
        _events.send(SubmissionListEvent.NavigateToCollection(id))
    }

    private suspend fun refreshStartableForms(): List<FormChoice> =
        catalog.startable().also { forms ->
            _state.update { it.copy(startableForms = forms) }
        }
}
