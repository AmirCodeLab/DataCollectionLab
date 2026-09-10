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
    onNavigateToSettings: () -> Unit,
    onNavigateToUpdates: () -> Unit = {},
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    ObserveAsEvents(viewModel.events) { event ->
        when (event) {
            is SubmissionListEvent.NavigateToCollection ->
                onNavigateToCollection(event.submissionId)
        }
    }

    SubmissionListScreen(
        state = state,
        onAction = viewModel::onAction,
        onNavigateToSettings = onNavigateToSettings,
        onNavigateToUpdates = onNavigateToUpdates,
    )
}

@Composable
fun SubmissionListScreen(
    state: SubmissionListState,
    onAction: (SubmissionListAction) -> Unit,
    onNavigateToSettings: () -> Unit = {},
    onNavigateToUpdates: () -> Unit = {},
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
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 16.dp, end = 8.dp, top = 16.dp, bottom = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Submissions",
                    style = MaterialTheme.typography.headlineSmall,
                    modifier = Modifier.weight(1f),
                )
                // The only route to the settings screen, and it has to be
                // reachable from the first screen after launch: a device
                // pointed at the wrong server cannot get past this one.
                TextButton(onClick = onNavigateToSettings) { Text("Settings") }
            }
            SyncBar(state = state, onAction = onAction)
            // A link, and deliberately not a third button. Sending a morning's
            // interviews and fetching a 38,000-row list are not the same kind
            // of decision, and a row of equal buttons says they are (item 4,
            // A1). One button on this screen; the choices are one tap away.
            if (state.updatesWaiting != null) {
                TextButton(
                    onClick = onNavigateToUpdates,
                    modifier = Modifier.padding(start = 8.dp),
                ) {
                    Text(state.updatesWaiting)
                }
            }
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

                state.emptyState != null -> Box(
                    modifier = Modifier.fillMaxSize().padding(24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    // Four situations wore one sentence before item 4, and two
                    // of them are not this person's to fix. "No submissions
                    // yet" said to someone nobody has assigned a case to sends
                    // them looking for a button that does not exist.
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = state.emptyState.text,
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            textAlign = TextAlign.Center,
                        )
                        if (state.emptyState.opensUpdates) {
                            TextButton(onClick = onNavigateToUpdates) { Text("Open Updates") }
                        }
                    }
                }

                else -> WorkList(state, onAction)
            }
        }
    }
}

/**
 * The cases first, then the submissions. A case is where fieldwork starts
 * for an enumerator with a sample (item 2): a tap opens the draft on it or
 * starts one. A released case with work on it stays listed, under its own
 * heading, so the draft is reachable and named — never silently gone.
 */
@Composable
private fun WorkList(state: SubmissionListState, onAction: (SubmissionListAction) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (state.caseRefusal != null) {
            item(key = "case-refusal") {
                Text(
                    text = state.caseRefusal,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(vertical = 4.dp),
                )
            }
        }
        if (state.assignedCases.isNotEmpty()) {
            item(key = "assigned-heading") {
                SectionHeading("Assigned to me (${state.assignedCases.size})")
            }
            items(items = state.assignedCases, key = { "case-" + it.caseId }) { case ->
                CaseCard(case = case, onClick = { onAction(SubmissionListAction.OnCaseClick(case.caseId)) })
            }
        }
        if (state.releasedCases.isNotEmpty()) {
            item(key = "released-heading") {
                SectionHeading("No longer assigned to you — drafts kept (${state.releasedCases.size})")
            }
            items(items = state.releasedCases, key = { "released-" + it.caseId }) { case ->
                CaseCard(case = case, onClick = { onAction(SubmissionListAction.OnCaseClick(case.caseId)) })
            }
        }
        if (state.submissions.isNotEmpty()) {
            item(key = "submissions-heading") {
                SectionHeading("Submissions (${state.submissions.size})")
            }
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

@Composable
private fun SectionHeading(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = 8.dp),
    )
}

@Composable
private fun CaseCard(case: CaseUi, onClick: () -> Unit) {
    Card(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = case.label, style = MaterialTheme.typography.titleMedium)
                if (case.summary.isNotEmpty()) {
                    Text(
                        text = case.summary,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.width(8.dp))
            SuggestionChip(
                onClick = onClick,
                label = {
                    Text(
                        when {
                            !case.assigned -> "No longer assigned"
                            case.submissions > 0 -> "In progress"
                            else -> "Start"
                        },
                    )
                },
            )
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
                // Named for what it does, now that it is not the only sync:
                // this one sends the answers and brings the assignments, and
                // it never waits for a form document or a village list.
                Text("Sync work")
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
                    if (submission.caseKey != null) {
                        Text(
                            text = if (submission.caseAssigned == false) {
                                "Case ${submission.caseKey} · no longer assigned to you"
                            } else {
                                "Case ${submission.caseKey}"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = if (submission.caseAssigned == false) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Spacer(Modifier.width(8.dp))
                SuggestionChip(
                    onClick = onClick,
                    label = {
                        Text(
                            when {
                                submission.returnedReason != null -> "Sent back"
                                submission.finalized -> "Finalized"
                                else -> "Draft"
                            }
                        )
                    },
                )
            }
            if (submission.returnedReason != null) {
                // The reason is on the row, not behind the tap. An enumerator
                // has to know what to change before deciding to open the form
                // again — a reason one tap further in is a reason half of them
                // will not have read, and the visit is repeated instead of
                // corrected (item 6).
                Text(
                    text = submission.returnedReason,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(top = 4.dp),
                )
                if (submission.returnedAt != null) {
                    Text(
                        // The decision's time, not this device's: a handset
                        // offline for a week must not report old news as new.
                        text = "Sent back ${submission.returnedAt}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
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
