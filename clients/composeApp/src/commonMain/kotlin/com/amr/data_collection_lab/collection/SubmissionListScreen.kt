package com.amr.data_collection_lab.collection

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun SubmissionListRoot(
    viewModel: SubmissionListViewModel,
    onNavigateToCollection: (String) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    ObserveAsEvents(viewModel.events) { event ->
        when (event) {
            is SubmissionListEvent.NavigateToCollection ->
                onNavigateToCollection(event.submissionId)
        }
    }

    SubmissionListScreen(state = state, onAction = viewModel::onAction)
}

@Composable
fun SubmissionListScreen(
    state: SubmissionListState,
    onAction: (SubmissionListAction) -> Unit,
) {
    Scaffold(
        contentWindowInsets = WindowInsets(0.dp),
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { onAction(SubmissionListAction.OnNewSubmissionClick) },
            ) {
                Text("New submission")
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            Text(
                text = "Submissions",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp),
            )
            SyncBar(state = state, onAction = onAction)
            HorizontalDivider()
            if (state.isChoosingForm) {
                FormPicker(
                    forms = state.startableForms,
                    onChoose = { onAction(SubmissionListAction.OnFormChosen(it)) },
                    onDismiss = { onAction(SubmissionListAction.OnFormChoiceDismissed) },
                )
            }
            when {
                state.isLoading -> Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) { CircularProgressIndicator() }

                state.submissions.isEmpty() -> Box(
                    modifier = Modifier.fillMaxSize().padding(24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        // Two different situations, and telling an enumerator
                        // the wrong one wastes their morning: with no forms the
                        // next step is a sync, not a tap on "New submission".
                        text = if (state.startableForms.isEmpty()) {
                            "No forms on this device yet. Tap Sync to get the forms " +
                                "your project has deployed."
                        } else {
                            "No submissions yet. Start one with “New submission”."
                        },
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                }

                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 96.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(items = state.submissions, key = { it.submissionId }) { submission ->
                        SubmissionCard(
                            submission = submission,
                            onClick = {
                                onAction(SubmissionListAction.OnSubmissionClick(submission.submissionId))
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SyncBar(state: SubmissionListState, onAction: (SubmissionListAction) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = if (state.pendingTotal == 0L) "All changes synced"
                else "${state.pendingTotal} ops waiting to sync",
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                text = state.lastSyncAt?.let { "Last sync $it" } ?: "Never synced",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (state.registrationFailure != null) {
                Text(
                    text = "Device not registered: ${state.registrationFailure}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            if (state.rejectedSummary != null) {
                Text(
                    text = state.rejectedSummary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            if (state.formError != null) {
                Text(
                    // Reported apart from lastSyncError because the sync did
                    // not fail: the answers moved and the forms did not.
                    text = "Forms not refreshed: ${state.formError}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary,
                )
            }
            if (state.lastSyncError != null) {
                Text(
                    text = state.lastSyncError,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        Spacer(Modifier.width(8.dp))
        Button(
            onClick = { onAction(SubmissionListAction.OnSyncClick) },
            enabled = !state.isSyncing,
        ) {
            if (state.isSyncing) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                )
            } else {
                Text("Sync")
            }
        }
    }
}

@Composable
private fun SubmissionCard(submission: SubmissionUi, onClick: () -> Unit) {
    Card(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = submission.formTitle,
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        // The version is not decoration: two drafts of the same
                        // form can be on different versions, and they are not
                        // the same questionnaire (Form IR §9).
                        text = "v${submission.formVersion} · ${submission.savedAt}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.width(8.dp))
                SuggestionChip(
                    onClick = onClick,
                    label = { Text(if (submission.finalized) "Finalized" else "Draft") },
                )
            }
            Text(
                text = "${submission.pendingOps} ops waiting to sync",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.tertiary,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

/**
 * Which form to start, for a device holding more than one.
 *
 * Only shown when there is a choice to make: one form starts straight away and
 * no form says so in the list instead. A dialog that always appears turns every
 * new interview into two taps for no information.
 */
@Composable
private fun FormPicker(
    forms: List<FormChoice>,
    onChoose: (FormChoice) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Which form?") },
        text = {
            Column {
                forms.forEach { form ->
                    TextButton(
                        onClick = { onChoose(form) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            text = "${form.title} · v${form.version}",
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

@Preview
@Composable
private fun SubmissionListScreenPreview() {
    MaterialTheme {
        SubmissionListScreen(
            state = SubmissionListState(
                isLoading = false,
                pendingTotal = 75,
                lastSyncAt = "2026-08-29 12:40",
                startableForms = listOf(FormChoice("household_survey", 2, "Household Survey")),
                submissions = listOf(
                    SubmissionUi("01A", "Household Survey", 2, "2026-08-29 10:12", false, 14),
                    SubmissionUi("01B", "Household Survey", 1, "2026-08-28 16:40", true, 61),
                ),
            ),
            onAction = {},
        )
    }
}

@Preview
@Composable
private fun SubmissionListNoFormsPreview() {
    MaterialTheme {
        SubmissionListScreen(state = SubmissionListState(isLoading = false), onAction = {})
    }
}
