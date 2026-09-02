package com.amr.data_collection_lab.collection

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun CollectionRoot(
    viewModel: CollectionViewModel,
    onNavigateBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    ObserveAsEvents(viewModel.events) { event ->
        when (event) {
            CollectionEvent.NavigateBack -> onNavigateBack()
        }
    }

    CollectionScreen(state = state, onAction = viewModel::onAction)
}

@Composable
fun CollectionScreen(
    state: CollectionState,
    onAction: (CollectionAction) -> Unit,
) {
    // RTL from the first version: the layout direction follows the selected form
    // language, and every arrangement below uses logical start/end only.
    val direction = if (isRtl(state.language)) LayoutDirection.Rtl else LayoutDirection.Ltr
    CompositionLocalProvider(LocalLayoutDirection provides direction) {
        // The viewfinder replaces the question list rather than sitting inside
        // it. A camera preview in a scrolling form is a viewfinder people
        // cannot aim, and on cheap handsets it is also a surface the
        // compositor struggles to keep smooth.
        val cameraPath = state.cameraForPath
        if (cameraPath != null) {
            CameraCaptureScreen(
                onCaptured = { onAction(CollectionAction.OnImageCaptured(cameraPath, it)) },
                onCancel = { onAction(CollectionAction.OnCameraCancelled) },
                onUnavailable = { onAction(CollectionAction.OnCaptureUnavailable(it)) },
            )
            return@CompositionLocalProvider
        }
        Scaffold(
            topBar = { CollectionTopBar(state, onAction) },
            bottomBar = { NavigationBar(state, onAction) },
            contentWindowInsets = WindowInsets(0.dp),
        ) { padding ->
            if (state.isLoading) {
                Box(
                    modifier = Modifier.fillMaxSize().padding(padding),
                    contentAlignment = Alignment.Center,
                ) { CircularProgressIndicator() }
                return@Scaffold
            }
            if (state.missingFormVersion != null) {
                // Reachable only if form retention failed (Form IR §9): the
                // store keeps every version a submission refers to. Rendering
                // an empty question list instead would be indistinguishable
                // from a submission whose answers were lost, and would be
                // reported as exactly that.
                Column(
                    modifier = Modifier.fillMaxSize().padding(padding).padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = "This submission cannot be opened",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        modifier = Modifier.padding(top = 8.dp),
                        text = "This device no longer holds ${state.missingFormVersion}, the " +
                            "form version these answers were collected under. The answers are " +
                            "safe and will still sync — only the questions are missing. Sync " +
                            "again, and report this if it persists.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                return@Scaffold
            }
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                if (state.screenTitle != null) {
                    item(key = "screen_title") {
                        Text(
                            text = state.screenTitle,
                            style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.padding(top = 16.dp),
                        )
                    }
                }
                if (state.captureMessage != null) {
                    // A refusal worth explaining — a GPS fix too imprecise to
                    // keep, a camera permission denied. Above the questions
                    // rather than beside one, because it is usually about the
                    // device and not about the answer.
                    item(key = "capture_message") {
                        Text(
                            text = state.captureMessage,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(top = 12.dp),
                        )
                    }
                }
                items(items = state.questions, key = { it.path }) { question ->
                    QuestionItem(
                        question = question,
                        language = state.language,
                        enabled = !state.finalized && !question.readOnly,
                        onAction = onAction,
                    )
                }
            }
        }
    }
}

@Composable
private fun CollectionTopBar(state: CollectionState, onAction: (CollectionAction) -> Unit) {
    Surface(shadowElevation = 2.dp) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = { onAction(CollectionAction.OnBackClick) }) {
                Text(UiStrings.back(state.language))
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = state.formTitle,
                    style = MaterialTheme.typography.titleMedium,
                )
                if (state.finalized) {
                    Text(
                        text = UiStrings.finalized(state.language),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.tertiary,
                    )
                }
            }
            if (state.languages.size > 1) {
                TextButton(onClick = { onAction(CollectionAction.OnLanguageToggle) }) {
                    Text(state.language.uppercase())
                }
            }
        }
    }
}

@Composable
private fun NavigationBar(state: CollectionState, onAction: (CollectionAction) -> Unit) {
    if (state.isLoading) return
    Surface(shadowElevation = 8.dp) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            if (state.showErrors && !state.canFinalize) {
                Text(
                    text = UiStrings.invalidRemaining(state.language, state.blockingCount),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(bottom = 8.dp),
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedButton(
                    onClick = { onAction(CollectionAction.OnPreviousClick) },
                    enabled = state.hasPrevious,
                ) {
                    Text(UiStrings.previous(state.language))
                }
                Text(
                    text = "${state.progressPosition} / ${state.progressTotal}",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f),
                )
                when {
                    state.hasNext -> Button(
                        onClick = { onAction(CollectionAction.OnNextClick) },
                    ) {
                        Text(UiStrings.next(state.language))
                    }
                    !state.finalized -> Button(
                        onClick = { onAction(CollectionAction.OnFinalizeClick) },
                    ) {
                        Text(UiStrings.finalize(state.language))
                    }
                    else -> Unit
                }
            }
        }
    }
}

@Composable
private fun QuestionItem(
    question: QuestionUi,
    language: String,
    enabled: Boolean,
    onAction: (CollectionAction) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = if (question.required) "${question.label} *" else question.label,
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        // Every branch here must have an entry in specs/collectable-types-v0.1.json
        // and every entry there must have a branch — CollectableTypesTest drives
        // this composable in both directions and fails on either drift.
        when (question.dataType) {
            "text" -> TextAnswer(question, enabled, KeyboardType.Text, onAction)
            "integer" -> TextAnswer(question, enabled, KeyboardType.Number, onAction)
            "decimal" -> TextAnswer(question, enabled, KeyboardType.Decimal, onAction)
            "select_one" -> SelectOneAnswer(question, enabled, onAction)
            "select_multiple" -> SelectMultipleAnswer(question, enabled, onAction)
            "date" -> DateAnswer(question, language, enabled, onAction)
            "note" -> Unit // Display only (§2.1): the label above is the whole widget.
            "image" -> ImageAnswer(question, language, enabled, onAction)
            "signature" -> SignatureAnswer(question, language, enabled, onAction)
            "geopoint" -> GeoPointAnswer(question, language, enabled, onAction)
            // The one that matters most, and the one that was missing. A form
            // deployed for a newer app version than this phone runs reaches
            // here, and it must be visibly unanswerable rather than blank — an
            // enumerator cannot otherwise tell "nothing to do" from "this build
            // cannot ask you this". Never a control that takes input and drops
            // it, which is defect 2's mistake.
            else -> UnsupportedAnswer(question, language)
        }
        val supporting = question.error ?: question.hint
        if (supporting != null) {
            Text(
                text = supporting,
                style = MaterialTheme.typography.bodySmall,
                color = if (question.error != null) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

@Composable
private fun TextAnswer(
    question: QuestionUi,
    enabled: Boolean,
    keyboardType: KeyboardType,
    onAction: (CollectionAction) -> Unit,
) {
    OutlinedTextField(
        value = question.displayText,
        onValueChange = { onAction(CollectionAction.OnTextChange(question.path, it)) },
        enabled = enabled,
        isError = question.error != null,
        singleLine = keyboardType != KeyboardType.Text,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        modifier = Modifier.fillMaxWidth(),
    )
}

/**
 * A question this build has no widget for (Form IR §2.1 has more dataTypes
 * than any one app version implements).
 *
 * Drawn as text, deliberately: there is no control, nothing focusable and
 * nothing that could be mistaken for an input. The alternative that keeps
 * being reached for — render a text box "so at least they can type something"
 * — collects a string where a barcode or a time belongs, and that is wrong in
 * a way nobody notices until fieldwork is over.
 */
@Composable
private fun UnsupportedAnswer(question: QuestionUi, language: String) {
    Text(
        text = UiStrings.unsupportedQuestionType(language, question.dataType),
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.error,
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
    )
}

/**
 * `select_multiple` (§2.1): zero or more choices, stored as a sequence.
 *
 * Order-insensitive per the spec, and the order the enumerator tapped in is not
 * meaningful — so the value is rebuilt in the form's own choice order on every
 * toggle rather than appended to. Two devices answering the same question the
 * same way then produce the same value, which matters because these are the
 * bytes that get encrypted and compared.
 */
@Composable
private fun SelectMultipleAnswer(
    question: QuestionUi,
    enabled: Boolean,
    onAction: (CollectionAction) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        question.choices.forEach { choice ->
            val checked = choice.value in question.selectedValues
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .toggleable(
                        value = checked,
                        enabled = enabled,
                        role = Role.Checkbox,
                        onValueChange = {
                            onAction(CollectionAction.OnChoiceToggle(question.path, choice.value))
                        },
                    )
                    .padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Checkbox(checked = checked, onCheckedChange = null, enabled = enabled)
                Text(
                    text = choice.label,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
        }
    }
}

@Composable
private fun SelectOneAnswer(
    question: QuestionUi,
    enabled: Boolean,
    onAction: (CollectionAction) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth().selectableGroup()) {
        question.choices.forEach { choice ->
            val selected = choice.value == question.selectedValue
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .selectable(
                        selected = selected,
                        enabled = enabled,
                        role = Role.RadioButton,
                        onClick = {
                            onAction(CollectionAction.OnChoiceSelect(question.path, choice.value))
                        },
                    )
                    .padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(selected = selected, onClick = null, enabled = enabled)
                Text(
                    text = choice.label,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DateAnswer(
    question: QuestionUi,
    language: String,
    enabled: Boolean,
    onAction: (CollectionAction) -> Unit,
) {
    // Dialog visibility is transient, Compose-owned UI state (like scroll position).
    var showPicker by remember { mutableStateOf(false) }

    Box(modifier = Modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = question.dateIso.orEmpty(),
            onValueChange = {},
            readOnly = true,
            enabled = enabled,
            isError = question.error != null,
            placeholder = { Text(UiStrings.pickDate(language)) },
            modifier = Modifier.fillMaxWidth(),
        )
        if (enabled) {
            Box(
                modifier = Modifier
                    .matchParentSize()
                    .selectable(selected = false, role = Role.Button) { showPicker = true },
            )
        }
    }

    if (showPicker) {
        val pickerState = rememberDatePickerState(
            initialSelectedDateMillis = isoDateToEpochMillis(question.dateIso),
        )
        DatePickerDialog(
            onDismissRequest = { showPicker = false },
            confirmButton = {
                TextButton(onClick = {
                    pickerState.selectedDateMillis?.let {
                        onAction(CollectionAction.OnDateSelect(question.path, epochMillisToIsoDate(it)))
                    }
                    showPicker = false
                }) { Text(UiStrings.ok(language)) }
            },
            dismissButton = {
                TextButton(onClick = {
                    onAction(CollectionAction.OnDateSelect(question.path, null))
                    showPicker = false
                }) { Text(UiStrings.clear(language)) }
            },
        ) {
            DatePicker(state = pickerState)
        }
    }
}

@Preview
@Composable
private fun CollectionScreenPreview() {
    MaterialTheme {
        CollectionScreen(
            state = CollectionState(
                isLoading = false,
                formTitle = "Household Survey",
                language = "en",
                languages = listOf("en", "ar"),
                screenTitle = "Demographics",
                progressPosition = 4,
                progressTotal = 35,
                hasPrevious = true,
                hasNext = true,
                questions = listOf(
                    QuestionUi(
                        path = "resp_age", dataType = "integer", label = "Age (completed years)",
                        hint = "Completed years", required = true, readOnly = false,
                        displayText = "130", selectedValue = null, choices = emptyList(),
                        dateIso = null, error = "Age must be between 0 and 120",
                    ),
                ),
            ),
            onAction = {},
        )
    }
}
