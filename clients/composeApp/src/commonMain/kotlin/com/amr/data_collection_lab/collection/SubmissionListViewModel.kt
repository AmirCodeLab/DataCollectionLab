package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dcp.core.sync.CaseStore
import com.dcp.core.sync.FormStore
import com.dcp.core.sync.PendingFetch
import com.dcp.core.sync.ReferenceData
import com.dcp.core.sync.formatBytes
import com.dcp.core.sync.RejectReasons
import com.dcp.core.sync.SubmissionStatus
import com.dcp.core.sync.SyncScope
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
    /**
     * What is waiting to be downloaded, if anything — a link, never a button
     * beside the work sync (item 4, A1). Null when there is nothing to choose.
     */
    val updatesWaiting: String? = null,
    /** What to say when there is nothing to show. See [EmptyState]. */
    val emptyState: EmptyState? = null,
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

/**
 * What the list says when it has nothing to list.
 *
 * Four different situations wore one sentence before item 4, and two of them
 * are not the enumerator's to fix. Telling somebody "no submissions yet" when
 * the truth is "nobody has assigned you a case" sends them looking for a
 * button that does not exist.
 */
data class EmptyState(
    val text: String,
    /** True when the person can act on it themselves, from Updates. */
    val opensUpdates: Boolean = false,
)

class SubmissionListViewModel(
    private val store: SubmissionStore,
    private val catalog: FormCatalog,
    private val syncClient: SyncClient,
    private val cases: CaseStore,
    private val forms: FormStore,
    private val referenceData: ReferenceData,
) : ViewModel() {

    private val _state = MutableStateFlow(SubmissionListState())
    val state = _state.asStateFlow()

    private val _events = Channel<SubmissionListEvent>()
    val events = _events.receiveAsFlow()

    init {
        viewModelScope.launch {
            refreshStartableForms()
            refreshShellState()
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
                refreshShellState()
            }
        }
        viewModelScope.launch {
            cases.observe().collect { held ->
                val sections = sectionsOf(held)
                _state.update {
                    it.copy(assignedCases = sections.assigned, releasedCases = sections.releasedWithWork)
                }
                refreshShellState()
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
                // `syncWork`, not `syncOnce`: the answers, the assignments and
                // both manifests, and not one form document or dataset row
                // (item 4, A1). This is the action a person must never have to
                // think twice about, so it is also the one that cannot
                // surprise them with a 38,000-row list.
                val result = withContext(Dispatchers.Default) { syncClient.syncWork() }
                _state.update {
                    it.copy(
                        registrationFailure = result.registrationFailure,
                        formError = result.formError,
                    )
                }
                // A sync is how forms arrive, so the picker's list is stale the
                // moment one finishes — and so is what is waiting to download.
                refreshStartableForms()
                refreshShellState()
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

    /**
     * What is waiting to be downloaded, and what it would cost — read from
     * local state, so it is answerable between syncs and offline.
     *
     * A link, not a button: the work sync is the one action on this screen,
     * and three peers would say that sending a morning's interviews is the
     * same kind of choice as fetching a village list (item 4, A1).
     */
    private suspend fun refreshShellState() {
        val snapshot = withContext(Dispatchers.Default) {
            Triple(
                forms.deployedNotHeld().size,
                referenceData.pendingFetches(),
                store.scopeStatuses().any {
                    it.scope == SyncScope.ASSIGNMENTS && it.lastOkAt != null
                },
            )
        }
        val (waitingForms, pending, assignmentsAnswered) = snapshot
        val current = _state.value
        _state.update {
            it.copy(
                updatesWaiting = waitingLine(waitingForms, pending),
                emptyState = if (current.submissions.isEmpty() &&
                    current.assignedCases.isEmpty() &&
                    current.releasedCases.isEmpty()
                ) {
                    emptyStateFor(
                        startable = current.startableForms.size,
                        waitingForms = waitingForms,
                        cases = current.assignedCases.size,
                        assignmentsAnswered = assignmentsAnswered,
                    )
                } else {
                    null
                },
            )
        }
    }

    private fun waitingLine(waitingForms: Int, pending: List<PendingFetch>): String? {
        run {
            if (waitingForms == 0 && pending.isEmpty()) return null
            val parts = buildList {
                if (waitingForms > 0) add(if (waitingForms == 1) "1 form" else "$waitingForms forms")
                if (pending.isNotEmpty()) {
                    add(if (pending.size == 1) "1 list" else "${pending.size} lists")
                }
            }
            // Only full downloads carry a number. A delta's size is not
            // knowable before it is asked for — the server does not know what
            // changed until it computes the diff — and an invented total on
            // this line would be the first thing a person stopped trusting.
            val fullBytes = pending
                .filter { it.deltaBaseVersion == null }
                .mapNotNull { it.estimatedFullBytes }
                .sum()
            val size = if (fullBytes > 0) " (about ${formatBytes(fullBytes)})" else ""
            return "Updates waiting: ${parts.joinToString(" and ")}$size"
        }
    }

}

/**
 * Which of the four empty states this is.
 *
 * Two of them are not this person's to fix, and saying so is the point:
 * an enumerator told "no submissions yet" when nobody has assigned them a
 * case goes looking for a button that does not exist.
 */
internal fun emptyStateFor(
    startable: Int,
    waitingForms: Int,
    cases: Int,
    assignmentsAnswered: Boolean,
): EmptyState = when {
    startable == 0 && waitingForms > 0 -> EmptyState(
        if (waitingForms == 1) "One form is deployed to this device and not downloaded yet."
        else "$waitingForms forms are deployed to this device and not downloaded yet.",
        opensUpdates = true,
    )
    startable == 0 -> EmptyState(
        "No form has been deployed to this device yet. A programme manager does that, " +
            "and there is nothing to collect until they have.",
    )
    assignmentsAnswered && cases == 0 -> EmptyState(
        "You hold no cases. A supervisor assigns them; they will appear here after a sync.",
    )
    else -> EmptyState("No submissions yet. Start one with \u201cNew submission\u201d.")
}
