package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.amr.data_collection_lab.todayIsoDate
import com.dcp.core.media.GeoCaptureOutcome
import com.dcp.core.media.MediaStore
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
private val SUPPORTED_TYPES = setOf(
    "text", "integer", "decimal", "select_one", "date",
    // Media (encryption envelope §6, sync §9). `audio`, `video` and `file` are
    // in the IR and are deliberately NOT here: capture for those is not built,
    // and rendering a widget that cannot answer the question would be worse
    // than skipping it, because the enumerator would think they had.
    "image", "signature", "geopoint",
)

/** How long typed input may sit before its op is committed. Keystrokes within
 * this window coalesce into one `set` op — ops record answers, not keystrokes. */
private const val TYPING_COMMIT_DELAY_MS = 400L

data class ChoiceUi(val value: String, val label: String)

/** A staged file, as the answer widget shows it. */
@Stable
data class MediaUi(
    val mediaId: String,
    val filename: String,
    /** "Saved on this device" / "Uploaded" / "Not uploaded yet: <reason>". */
    val status: String,
)

/** A captured position, with the honest account of how good it is. */
@Stable
data class GeoUi(
    val coordinates: String,
    val accuracyText: String,
    /**
     * Whether it met the project's threshold. A rejected reading is still shown
     * — with its accuracy — because "no location" and "a two-kilometre
     * location" need different things from the enumerator, and only one of them
     * is fixed by walking outside.
     */
    val accepted: Boolean,
)

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
    /**
     * The chosen values of a `select_multiple` (§2.1), in the form's own choice
     * order rather than the order they were tapped — the spec calls the value
     * order-insensitive, and a stable order is what makes two devices answering
     * alike produce identical bytes to encrypt and compare.
     */
    val selectedValues: List<String> = emptyList(),
    val choices: List<ChoiceUi>,
    val dateIso: String?,
    val error: String?,
    /** Set for an answered image or signature question. */
    val media: MediaUi? = null,
    /** Set for an answered geopoint question. */
    val geo: GeoUi? = null,
    /** True while a position fix is being waited for. */
    val capturing: Boolean = false,
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
    /** Whether the shared navigator will allow finalisation (spec 6.2).
     * Not the same as "every answer is valid": a soft constraint is invalid
     * and does not block. */
    val canFinalize: Boolean = false,
    /** How many fields stand in the way, for the refusal message. */
    val blockingCount: Int = 0,
    val showErrors: Boolean = false,
    /**
     * The question whose viewfinder is open, or null. A full screen rather than
     * an inline preview: a camera inside a scrolling form is a viewfinder people
     * cannot aim.
     */
    val cameraForPath: String? = null,
    /** A one-line message under the question, for a refusal worth explaining. */
    val captureMessage: String? = null,
    /**
     * Names the form version this device does not hold, when a submission
     * cannot be opened at all (Form IR §9).
     *
     * This is reachable only if retention failed: `FormStore.prune` keeps every
     * version a submission refers to, precisely so that this stays empty. It is
     * here because the alternative — rendering a form with no questions — is a
     * submission that looks answered-and-empty, which is indistinguishable from
     * real data loss and would be reported as such.
     */
    val missingFormVersion: String? = null,
)

sealed interface CollectionAction {
    data class OnTextChange(val path: String, val text: String) : CollectionAction
    /** Open the viewfinder for this question. */
    data class OnOpenCamera(val path: String) : CollectionAction
    data object OnCameraCancelled : CollectionAction
    /** The camera or the location service cannot be used, and why. */
    data class OnCaptureUnavailable(val reason: String) : CollectionAction
    /** JPEG bytes from the camera or the gallery, uncompressed as captured. */
    data class OnImageCaptured(val path: String, val bytes: ByteArray) : CollectionAction
    /** RGBA8888 pixels from the signature canvas. */
    data class OnSignatureDrawn(
        val path: String,
        val pixels: ByteArray,
        val width: Int,
        val height: Int,
    ) : CollectionAction
    data class OnClearMedia(val path: String) : CollectionAction
    data class OnCaptureLocation(val path: String) : CollectionAction
    data class OnClearGeoPoint(val path: String) : CollectionAction
    data class OnChoiceSelect(val path: String, val value: String) : CollectionAction
    /** Add or remove one value of a `select_multiple`. */
    data class OnChoiceToggle(val path: String, val value: String) : CollectionAction
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
    /**
     * Media capture. Null on a build with no media staging — the desktop
     * review client — where image, signature and geopoint questions render as
     * "not available on this device" rather than as a widget that cannot
     * answer them.
     */
    private val mediaCapture: MediaCaptureGraph? = null,
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
            val summaryFirst = withContext(Dispatchers.Default) { store.getSubmission(submissionId) }
            // Resolved from the submission by the catalog, never chosen here.
            // Form IR §9 binds a submission to the version it was collected
            // under, and this ViewModel is deliberately given no version it
            // could get wrong — see FormCatalog.compiledFormForSubmission.
            val compiled = catalog.compiledFormForSubmission(submissionId)
            if (compiled == null) {
                // The device does not hold that version. Nothing useful can be
                // rendered — the op log has the answers and not the questions —
                // so say which version is missing rather than showing an empty
                // form that looks like a submission with nothing in it.
                _state.update {
                    it.copy(
                        isLoading = false,
                        formTitle = summaryFirst?.formId ?: "Unknown form",
                        missingFormVersion = summaryFirst
                            ?.let { s -> "${s.formId} v${s.formVersion}" }
                            ?: submissionId,
                    )
                }
                return@launch
            }
            val (loadedInstance, summary) = withContext(Dispatchers.Default) {
                val inst = FormInstance(compiled, today = todayIsoDate())
                val stored = store.materialisedAnswers(submissionId)
                    .filterKeys { it in inst.values }
                if (stored.isNotEmpty()) inst.setMany(stored)
                inst to summaryFirst
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
            is CollectionAction.OnChoiceToggle -> onChoiceToggle(action.path, action.value)
            is CollectionAction.OnDateSelect ->
                commit(action.path, action.iso?.let { FormValue.Text(it) } ?: FormValue.Null,
                    debounce = false)
            CollectionAction.OnNextClick -> move { navigator.next() }
            CollectionAction.OnPreviousClick -> move { navigator.previous() }
            CollectionAction.OnLanguageToggle -> toggleLanguage()
            CollectionAction.OnFinalizeClick -> finalize()
            is CollectionAction.OnOpenCamera ->
                _state.update { it.copy(cameraForPath = action.path, captureMessage = null) }
            CollectionAction.OnCameraCancelled ->
                _state.update { it.copy(cameraForPath = null) }
            is CollectionAction.OnCaptureUnavailable ->
                _state.update { it.copy(cameraForPath = null, captureMessage = action.reason) }
            is CollectionAction.OnImageCaptured -> onImageCaptured(action.path, action.bytes)
            is CollectionAction.OnSignatureDrawn ->
                onSignatureDrawn(action.path, action.pixels, action.width, action.height)
            is CollectionAction.OnClearMedia -> onClearMedia(action.path)
            is CollectionAction.OnCaptureLocation -> onCaptureLocation(action.path)
            is CollectionAction.OnClearGeoPoint ->
                commit(action.path, FormValue.Null, debounce = false)
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

    /**
     * Toggle one value of a `select_multiple`.
     *
     * The result is rebuilt from the question's own choice order rather than by
     * appending or removing in place: §2.1 calls the value order-insensitive, so
     * two enumerators who tick the same boxes in a different order must produce
     * the same sequence. An empty selection is [FormValue.Null], not an empty
     * sequence — "nothing ticked" is an unanswered question, and the two are
     * different to `required` (§4.4).
     */
    private fun onChoiceToggle(path: String, value: String) {
        val current = (instance.states[path]?.value as? FormValue.Sequence)
            ?.items.orEmpty()
            .mapNotNull { (it as? FormValue.Text)?.value }
            .toSet()
        val next = if (value in current) current - value else current + value
        val ordered = choiceOrderFor(path).filter { it in next }
        commit(
            path,
            if (ordered.isEmpty()) FormValue.Null
            else FormValue.Sequence(ordered.map { FormValue.Text(it) }),
            debounce = false,
        )
    }

    /** The question's choice values, in document order. */
    private fun choiceOrderFor(path: String): List<String> =
        instance.form.fields[path]?.node?.choices?.items.orEmpty().map { it.value }

    private fun commit(path: String, value: FormValue, debounce: Boolean) {
        if (!ready() || _state.value.finalized) return
        touched += path
        if (value != instance.values[path]) {
            instance.set(path, value)
            queueOp(path, value, if (debounce) TYPING_COMMIT_DELAY_MS else 0L)
        }
        rebuild()
    }

    // -- media -------------------------------------------------------------

    /**
     * A photograph, from the camera or the gallery.
     *
     * Compressed to the project's settings, then staged — which encrypts it and
     * writes the `set` op naming it, in that order. The plaintext bytes are
     * never written anywhere: they go from this parameter through the
     * compressor into the cipher (encryption envelope §6, and the staging
     * pipeline in shared/core).
     */
    private fun onImageCaptured(path: String, bytes: ByteArray) {
        val media = mediaCapture ?: return
        _state.update { it.copy(cameraForPath = null) }
        viewModelScope.launch {
            val compressed = try {
                val policy = media.store.policy()
                withContext(Dispatchers.Default) {
                    media.compressor.compressJpeg(
                        bytes, policy.imageMaxDimension, policy.imageQuality,
                    )
                }
            } catch (cause: Exception) {
                // Not staged and no op written, so the question stays
                // unanswered — which is the truth. Silently staging the
                // uncompressed original instead would blow the project's
                // bandwidth budget with nothing saying so.
                _state.update {
                    it.copy(captureMessage = cause.message ?: "the image could not be read")
                }
                return@launch
            }
            stage(path, compressed, "photo.jpg", "image/jpeg")
        }
    }

    /** A signature, rasterised by the canvas and encoded to PNG here. */
    private fun onSignatureDrawn(path: String, pixels: ByteArray, width: Int, height: Int) {
        val media = mediaCapture ?: return
        viewModelScope.launch {
            val png = try {
                withContext(Dispatchers.Default) { media.encoder.encodePng(pixels, width, height) }
            } catch (cause: Exception) {
                _state.update {
                    it.copy(captureMessage = cause.message ?: "the signature could not be saved")
                }
                return@launch
            }
            stage(path, png, "signature.png", "image/png")
        }
    }

    /**
     * Stages the bytes and replaces whatever was there.
     *
     * The previous file is forgotten only after the new one is staged: the
     * other order would leave the question briefly answered by a file that no
     * longer exists, and a crash in between would make that permanent.
     */
    private suspend fun stage(path: String, bytes: ByteArray, filename: String, mimeType: String) {
        val media = mediaCapture ?: return
        val previous = media.store.forSubmission(submissionId)
            .firstOrNull { it.fieldPath == path && !it.uploaded }
        val staged = try {
            media.staging.captureInto(
                submissionId = submissionId,
                formId = form.formId,
                formVersion = form.version,
                fieldPath = path,
                filename = filename,
                mimeType = mimeType,
                plaintext = bytes,
                crypto = store.projectCrypto(),
            )
        } catch (cause: Exception) {
            _state.update {
                it.copy(captureMessage = cause.message ?: "the file could not be saved")
            }
            return
        }
        // Only now: the answer has a file behind it.
        previous?.let { media.staging.forget(it.mediaId) }

        touched += path
        instance.set(path, staged.reference().toFormValue())
        _state.update { it.copy(captureMessage = null) }
        rebuild()
    }

    /**
     * Clears a media answer.
     *
     * The staged file is dropped only when the server has not sealed it. Once
     * it has, the bytes are gone from the device anyway and the row is history
     * — the `unset` op is what records that the answer was removed, and
     * deleting the row would erase the fact that a file was ever there.
     */
    private fun onClearMedia(path: String) {
        val media = mediaCapture
        if (media != null) {
            media.store.forSubmission(submissionId)
                .filter { it.fieldPath == path && !it.uploaded }
                .forEach { media.staging.forget(it.mediaId) }
        }
        commit(path, FormValue.Null, debounce = false)
    }

    /**
     * Captures a position, held to the project's accuracy threshold.
     *
     * A reading worse than the threshold is NOT stored. It is shown, with its
     * accuracy and what the project needs, because a phone under a tin roof
     * reports a two-kilometre fix with exactly the authority of a good one, and
     * once it is in the data nothing downstream can tell them apart.
     */
    private fun onCaptureLocation(path: String) {
        val media = mediaCapture ?: return
        if (_state.value.finalized) return
        setCapturing(path, true)
        viewModelScope.launch {
            val lang = _state.value.language
            val required = media.store.policy().gpsMaxAccuracyM
            val outcome = media.geo.capture()
            setCapturing(path, false)
            when (outcome) {
                is GeoCaptureOutcome.Accepted -> {
                    _state.update { it.copy(captureMessage = null) }
                    commit(path, outcome.fix.toFormValue(), debounce = false)
                }
                is GeoCaptureOutcome.TooImprecise -> {
                    val accuracy = outcome.fix.accuracyM
                    _state.update {
                        it.copy(
                            captureMessage = if (accuracy == null) {
                                UiStrings.accuracyUnknown(lang, required)
                            } else {
                                UiStrings.accuracyTooPoor(lang, accuracy.toInt(), required)
                            }
                        )
                    }
                }
                GeoCaptureOutcome.TimedOut ->
                    _state.update { it.copy(captureMessage = UiStrings.positionTimedOut(lang)) }
                is GeoCaptureOutcome.Unavailable ->
                    _state.update { it.copy(captureMessage = outcome.reason) }
            }
        }
    }

    private val capturingPaths = mutableSetOf<String>()

    private fun setCapturing(path: String, active: Boolean) {
        if (active) capturingPaths += path else capturingPaths -= path
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

    /**
     * Finalisation is the one gate in the form (spec 6.2) — navigation is
     * never gated — and the shared navigator owns it. Asking `instance.isValid`
     * here instead would put the rule in one client: it would also refuse a
     * submission whose only fault is a soft constraint, which is meant to be
     * overridable.
     */
    private fun finalize() {
        if (!ready() || _state.value.finalized) return
        flushAllOps()
        if (!navigator.canFinalize) {
            // Show the errors and go to the question causing the refusal —
            // "3 answers still need attention" on a screen with none of them
            // on it leaves the enumerator hunting. goToFirstBlocking can
            // decline (a blocker inside a repeat has no screen), which is why
            // canFinalize above is what decides, not this.
            _state.update { it.copy(showErrors = true) }
            navigator.goToFirstBlocking()
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
                canFinalize = navigator.canFinalize,
                blockingCount = navigator.finalizationBlockers.size,
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
            selectedValues = (fieldState.value as? FormValue.Sequence)
                ?.items.orEmpty()
                .mapNotNull { (it as? FormValue.Text)?.value },
            choices = node.choices?.items.orEmpty().map {
                ChoiceUi(it.value, it.label.resolve(lang) ?: it.value)
            },
            dateIso = textValue,
            error = error,
            media = mediaUi(node, fieldState.value, lang),
            geo = geoUi(fieldState.value, lang),
            capturing = node.id in capturingPaths,
        )
    }

    /**
     * What the answer widget says about a staged file.
     *
     * Driven by the engine's value first: the answer is the media reference in
     * the op log, and the local `media` row is where the upload state lives. A
     * row with no matching answer is a capture that was replaced or cleared,
     * and must not show as the current answer.
     */
    private fun mediaUi(node: QuestionNode, value: FormValue, lang: String): MediaUi? {
        if (node.dataType != "image" && node.dataType != "signature") return null
        val reference = value as? FormValue.MediaRef ?: return null
        val row = mediaCapture?.store?.get(reference.id)
        return MediaUi(
            mediaId = reference.id,
            filename = reference.filename,
            status = when {
                row == null || row.uploaded -> UiStrings.mediaUploaded(lang)
                row.lastError != null -> UiStrings.mediaUploadFailed(lang, row.lastError!!)
                else -> UiStrings.mediaStaged(lang)
            },
        )
    }

    /**
     * A captured point, and how good it is.
     *
     * Only an accepted reading is ever an answer — [onCaptureLocation] refuses
     * the rest — so anything showing here met the threshold at the time it was
     * taken. It still displays its accuracy, because a project that later
     * tightens the threshold has not made this reading worse, and the number is
     * how a reviewer can tell.
     */
    private fun geoUi(value: FormValue, lang: String): GeoUi? {
        val point = value as? FormValue.GeoPoint ?: return null
        val accuracy = point.accuracy
        val required = mediaCapture?.store?.policy()?.gpsMaxAccuracyM
        return GeoUi(
            coordinates = formatCoordinate(point.lat) + ", " + formatCoordinate(point.lon),
            accuracyText = when {
                accuracy == null -> UiStrings.accuracyUnknown(lang, required ?: 0)
                required != null && accuracy > required ->
                    UiStrings.accuracyTooPoor(lang, accuracy.toInt(), required)
                else -> UiStrings.accuracyOk(lang, accuracy.toInt())
            },
            accepted = accuracy != null && (required == null || accuracy <= required),
        )
    }

    /**
     * Six decimal places — about 0.1 m at the equator, which is finer than any
     * handset GPS and coarse enough not to imply a precision that is not there.
     */
    private fun formatCoordinate(degrees: Double): String {
        val scaled = kotlin.math.round(degrees * 1_000_000.0).toLong()
        val whole = scaled / 1_000_000
        val fraction = kotlin.math.abs(scaled % 1_000_000).toString().padStart(6, '0')
        val sign = if (scaled < 0 && whole == 0L) "-" else ""
        return "$sign$whole.$fraction"
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
