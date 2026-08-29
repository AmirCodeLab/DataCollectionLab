package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dcp.core.sync.SubmissionStatus
import com.dcp.core.sync.SubmissionStore
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

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
)

sealed interface SubmissionListAction {
    data object OnNewSubmissionClick : SubmissionListAction
    data class OnSubmissionClick(val submissionId: String) : SubmissionListAction
}

sealed interface SubmissionListEvent {
    data class NavigateToCollection(val submissionId: String) : SubmissionListEvent
}

class SubmissionListViewModel(
    private val store: SubmissionStore,
    private val catalog: FormCatalog,
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
    }

    fun onAction(action: SubmissionListAction) {
        when (action) {
            is SubmissionListAction.OnNewSubmissionClick -> viewModelScope.launch {
                val form = catalog.compiledForm()
                val id = store.createDraft(form.formId, form.version)
                _events.send(SubmissionListEvent.NavigateToCollection(id))
            }
            is SubmissionListAction.OnSubmissionClick -> viewModelScope.launch {
                _events.send(SubmissionListEvent.NavigateToCollection(action.submissionId))
            }
        }
    }
}
