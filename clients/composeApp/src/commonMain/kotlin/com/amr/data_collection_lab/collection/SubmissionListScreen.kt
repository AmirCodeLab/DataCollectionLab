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
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
                        text = "No submissions yet. Start one with “New submission”.",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                        text = submission.savedAt,
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

@Preview
@Composable
private fun SubmissionListScreenPreview() {
    MaterialTheme {
        SubmissionListScreen(
            state = SubmissionListState(
                isLoading = false,
                pendingTotal = 75,
                lastSyncAt = "2026-08-29 12:40",
                submissions = listOf(
                    SubmissionUi("01A", "Household Survey", "2026-08-29 10:12", false, 14),
                    SubmissionUi("01B", "Household Survey", "2026-08-28 16:40", true, 61),
                ),
            ),
            onAction = {},
        )
    }
}
