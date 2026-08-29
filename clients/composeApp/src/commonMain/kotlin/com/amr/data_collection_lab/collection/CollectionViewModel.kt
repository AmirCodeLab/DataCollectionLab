package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.amr.data_collection_lab.todayIsoDate
import com.dcp.core.sync.OpKind
import com.dcp.core.sync.SubmissionStatus
import com.dcp.core.sync.SubmissionStore
import com.dcp.form.CompiledForm
import com.dcp.form.FormInstance
import com.dcp.form.FormNavigator
import com.dcp.form.FormValue
import com.dcp.form.QuestionNode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** The question types this slice renders. Everything else is skipped. */
private val SUPPORTED_TYPES = setOf("text", "integer", "decimal", "select_one", "date")

/** How long typed input may sit before its op is committed. Keystrokes within
 * this window coalesce into one `set` op — ops record answers, not keystrokes. */
private const val TYPING_COMMIT_DELAY_MS = 400L

data class ChoiceUi(val value: String, val label: String)

@Stable
data class QuestionUi(
    val path: String,
    val dataType: String,
    val label: String,
    val hint: String?,
    val required: Boolean,
    val readOnly: Boolean,
    val displayText: String,
    val selectedValue: String?,
    val choices: List<ChoiceUi>,
    val dateIso: String?,
    val error: String?,
)

@Stable
data class CollectionState(
    val isLoading: Boolean = true,
    val formTitle: String = "",
    val language: String = "en",
    val languages: List<String> = emptyList(),
    /** Questions of the current screen only — the shared navigator decides
     * which screen that is; the UI never computes screen flow. */
    val questions: List<QuestionUi> = emptyList(),
    val screenTitle: String? = null,
    val progressPosition: Int = 0,
    val progressTotal: Int = 0,
    val hasPrevious: Boolean = false,
    val hasNext: Boolean = false,
    val finalized: Boolean = false,
    val isValid: Boolean = false,
    val invalidCount: Int = 0,
    val showErrors: Boolean = false,
)

sealed interface CollectionAction {
    data class OnTextChange(val path: String, val text: String) : CollectionAction
    data class OnChoiceSelect(val path: String, val value: String) : CollectionAction
    data class OnDateSelect(val path: String, val iso: String?) : CollectionAction
    data object OnNextClick : CollectionAction
    data object OnPreviousClick : CollectionAction
    data object OnLanguageToggle : CollectionAction
    data object OnFinalizeClick : CollectionAction
    data object OnBackClick : CollectionAction
}

sealed interface CollectionEvent {
    data object NavigateBack : CollectionEvent
}

/**
 * Drives one open submission.
 *
 * All form semantics (relevance, constraints, required, calculations) come from
 * the shared engine's [FormInstance], and screen flow — which screen is
 * current, what is next, what is previous — from the shared [FormNavigator].
 * This class only converts raw widget input into typed [FormValue]s, records
 * sync ops, and projects engine state into UI models. Any behaviour added here
 * instead of the shared layer will not exist on iOS, desktop or web.
 */
class CollectionViewModel(
    private val store: SubmissionStore,
    private val catalog: FormCatalog,
    private val submissionId: String,
) : ViewModel() {

    private val _state = MutableStateFlow(CollectionState())
    val state = _state.asStateFlow()

    private val _events = Channel<CollectionEvent>()
    val events = _events.receiveAsFlow()

    private lateinit var form: CompiledForm
    private lateinit var instance: FormInstance
    private lateinit var navigator: FormNavigator

    /** Raw text as typed, per path — kept so "3." doesn't render back as "3". */
    private val drafts = mutableMapOf<String, String>()
    private val touched = mutableSetOf<String>()

    /** Values whose op has not been written yet, and the debounce job per path.
     * Everything runs on the main dispatcher, so op order follows user order. */
    private val pendingOps = mutableMapOf<String, FormValue>()
    private val commitJobs = mutableMapOf<String, Job>()

    init {
        viewModelScope.launch {
            val compiled = catalog.compiledForm()
            val (loadedInstance, summary) = withContext(Dispatchers.Default) {
                val inst = FormInstance(compiled, today = todayIsoDate())
                val stored = store.materialisedAnswers(submissionId)
                    .filterKeys { it in inst.values }
                if (stored.isNotEmpty()) inst.setMany(stored)
                inst to store.getSubmission(submissionId)
            }
            form = compiled
            instance = loadedInstance
            navigator = FormNavigator(instance)
            val language = compiled.ir.defaultLanguage
                ?: compiled.ir.languages.firstOrNull() ?: "en"
            _state.update {
                it.copy(
                    isLoading = false,
                    language = language,
                    languages = compiled.ir.languages,
                    formTitle = compiled.ir.title.resolve(language) ?: compiled.formId,
                    finalized = summary?.status == SubmissionStatus.FINALIZED,
                )
            }
            rebuild()
        }
    }

    fun onAction(action: CollectionAction) {
        when (action) {
            is CollectionAction.OnTextChange -> onTextChange(action.path, action.text)
            is CollectionAction.OnChoiceSelect -> onChoiceSelect(action.path, action.value)
            is CollectionAction.OnDateSelect ->
                commit(action.path, action.iso?.let { FormValue.Text(it) } ?: FormValue.Null,
                    debounce = false)
            CollectionAction.OnNextClick -> move { navigator.next() }
            CollectionAction.OnPreviousClick -> move { navigator.previous() }
            CollectionAction.OnLanguageToggle -> toggleLanguage()
            CollectionAction.OnFinalizeClick -> finalize()
            CollectionAction.OnBackClick -> viewModelScope.launch {
                flushAllOps()
                _events.send(CollectionEvent.NavigateBack)
            }
        }
    }

    // -- screen navigation -------------------------------------------------

    private fun move(step: () -> Boolean) {
        if (!ready()) return
        // leaving a screen marks its questions touched so errors show on return
        navigator.currentScreen?.questionIds?.let(touched::addAll)
        if (step()) rebuild()
    }

    // -- answering ---------------------------------------------------------

    private fun onTextChange(path: String, text: String) {
        val dataType = form.fields[path]?.dataType ?: return
        drafts[path] = text
        val trimmed = text.trim()
        val value = when {
            trimmed.isEmpty() -> FormValue.Null
            dataType == "integer" -> trimmed.toLongOrNull()?.let { FormValue.Integer(it) }
                ?: FormValue.Null
            dataType == "decimal" -> trimmed.toDoubleOrNull()?.let { FormValue.Decimal(it) }
                ?: FormValue.Null
            else -> FormValue.Text(text)
        }
        commit(path, value, debounce = true)
    }

    private fun onChoiceSelect(path: String, value: String) {
        // tapping the selected choice again clears the answer
        val current = (instance.states[path]?.value as? FormValue.Text)?.value
        commit(
            path,
            if (current == value) FormValue.Null else FormValue.Text(value),
            debounce = false,
        )
    }

    private fun commit(path: String, value: FormValue, debounce: Boolean) {
        if (!ready() || _state.value.finalized) return
        touched += path
        if (value != instance.values[path]) {
            instance.set(path, value)
            queueOp(path, value, if (debounce) TYPING_COMMIT_DELAY_MS else 0L)
        }
        rebuild()
    }

    // -- op log ------------------------------------------------------------

    private fun queueOp(path: String, value: FormValue, delayMs: Long) {
        pendingOps[path] = value
        commitJobs.remove(path)?.cancel()
        if (delayMs == 0L) {
            flushOp(path)
        } else {
            commitJobs[path] = viewModelScope.launch {
                delay(delayMs)
                commitJobs.remove(path)
                flushOp(path)
            }
        }
    }

    private fun flushOp(path: String) {
        val value = pendingOps.remove(path) ?: return
        store.appendOp(
            submissionId = submissionId,
            formId = form.formId,
            formVersion = form.version,
            kind = if (value == FormValue.Null) OpKind.UNSET else OpKind.SET,
            path = path,
            value = value.takeUnless { it == FormValue.Null },
        )
    }

    private fun flushAllOps() {
        commitJobs.values.forEach(Job::cancel)
        commitJobs.clear()
        pendingOps.keys.toList().forEach(::flushOp)
    }

    override fun onCleared() {
        // last line of durability: the op log is the only persistence there is
        flushAllOps()
    }

    // -- finalize ----------------------------------------------------------

    private fun finalize() {
        if (!ready() || _state.value.finalized) return
        flushAllOps()
        if (!instance.isValid) {
            _state.update { it.copy(showErrors = true) }
            rebuild()
            return
        }
        store.appendOp(
            submissionId = submissionId,
            formId = form.formId,
            formVersion = form.version,
            kind = OpKind.FINALIZE,
        )
        _state.update { it.copy(finalized = true) }
        viewModelScope.launch { _events.send(CollectionEvent.NavigateBack) }
    }

    // -- projection --------------------------------------------------------

    private fun toggleLanguage() {
        val languages = _state.value.languages
        if (languages.size < 2) return
        val next = languages[(languages.indexOf(_state.value.language) + 1) % languages.size]
        _state.update {
            it.copy(language = next, formTitle = form.ir.title.resolve(next) ?: form.formId)
        }
        rebuild()
    }

    private fun ready() = ::navigator.isInitialized

    private fun rebuild() {
        if (!ready()) return
        val lang = _state.value.language
        val showErrors = _state.value.showErrors

        val screen = navigator.currentScreen
        val questions = screen?.questionIds.orEmpty().mapNotNull { qid ->
            form.fields[qid]?.node?.let { questionUi(it, lang, showErrors) }
        }
        val titleGroupId = screen?.groupId ?: screen?.sectionId
        val (position, total) = navigator.progress()

        _state.update {
            it.copy(
                questions = questions,
                screenTitle = titleGroupId?.let { gid ->
                    form.containers[gid]?.label.resolve(lang)
                },
                progressPosition = position,
                progressTotal = total,
                hasPrevious = navigator.hasPrevious,
                hasNext = navigator.hasNext,
                isValid = instance.isValid,
                invalidCount = instance.states.values.count { s -> s.relevant && !s.valid },
            )
        }
    }

    private fun questionUi(node: QuestionNode, lang: String, showErrors: Boolean): QuestionUi? {
        if (node.dataType !in SUPPORTED_TYPES) return null
        val fieldState = instance.states[node.id] ?: return null
        if (!fieldState.relevant) return null

        val textValue = (fieldState.value as? FormValue.Text)?.value
        val error = if (showErrors || node.id in touched) {
            fieldState.errors.firstOrNull()?.let { err ->
                when (err.kind) {
                    "required" -> UiStrings.requiredAnswer(lang)
                    else -> err.message.resolve(lang) ?: UiStrings.invalidAnswer(lang)
                }
            }
        } else null

        return QuestionUi(
            path = node.id,
            dataType = node.dataType,
            label = node.label.resolve(lang) ?: node.id,
            hint = node.hint.resolve(lang),
            required = fieldState.required,
            readOnly = fieldState.readOnly,
            displayText = drafts[node.id] ?: formatValue(fieldState.value),
            selectedValue = textValue,
            choices = node.choices?.items.orEmpty().map {
                ChoiceUi(it.value, it.label.resolve(lang) ?: it.value)
            },
            dateIso = textValue,
            error = error,
        )
    }

    private fun formatValue(value: FormValue): String = when (value) {
        is FormValue.Null -> ""
        is FormValue.Text -> value.value
        is FormValue.Integer -> value.value.toString()
        is FormValue.Decimal ->
            if (value.value % 1.0 == 0.0) value.value.toLong().toString()
            else value.value.toString()
        is FormValue.DateValue -> value.iso
        else -> ""
    }
}
