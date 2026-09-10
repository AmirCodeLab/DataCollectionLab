package com.amr.data_collection_lab.collection

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun UpdatesRoot(viewModel: UpdatesViewModel, onNavigateBack: () -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    UpdatesScreen(state = state, onAction = viewModel::onAction, onNavigateBack = onNavigateBack)
}

/**
 * The two updates a person chooses (item 4), and what each will cost.
 *
 * Their work is not here, deliberately. It is sent from the submissions
 * screen, by the one button on it, and it is never held back by anything on
 * this screen — a layout that offered all three as peers would invite exactly
 * the trade nobody wants: a morning's interviews deferred to save bytes.
 */
@Composable
fun UpdatesScreen(
    state: UpdatesState,
    onAction: (UpdatesAction) -> Unit,
    onNavigateBack: () -> Unit = {},
) {
    Scaffold(contentWindowInsets = WindowInsets(0.dp)) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(start = 8.dp, end = 16.dp, top = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onNavigateBack) { Text("Back") }
                Text(text = "Updates", style = MaterialTheme.typography.headlineSmall)
            }
            Text(
                text = "Your interviews are sent from the Submissions screen and never wait " +
                    "for anything here.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
            HorizontalDivider()

            if (state.outcome != null) {
                Text(
                    text = state.outcome,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(16.dp),
                )
            }
            if (state.error != null) {
                Text(
                    text = state.error,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(16.dp),
                )
            }

            Section(title = "Forms", status = state.formsStatus)
            if (state.forms.isEmpty()) {
                Settled("Every form deployed to this device is downloaded.")
            } else {
                Card(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        state.forms.forEach { form ->
                            Text(
                                text = "${form.title} v${form.version} — waiting to download",
                                style = MaterialTheme.typography.bodyLarge,
                            )
                        }
                        Text(
                            text = "A form is tens of kilobytes.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        ActionButton(
                            label = "Update forms",
                            busy = state.busy == "forms",
                            enabled = state.busy == null,
                            onClick = { onAction(UpdatesAction.OnUpdateForms) },
                        )
                    }
                }
            }

            Section(title = "Reference data", status = state.listsStatus)
            if (state.lists.isEmpty()) {
                Settled("Every list your forms use is on this device.")
            } else {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    state.lists.forEach { list ->
                        Card(modifier = Modifier.fillMaxWidth()) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = list.statusLine,
                                    style = MaterialTheme.typography.bodyLarge,
                                )
                                // The cost, immediately under the name and
                                // above the button: this is the decision.
                                Text(
                                    text = list.costLine,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
                                )
                                ActionButton(
                                    label = if (list.partial) "Resume" else "Download",
                                    busy = state.busy == list.datasetKey,
                                    enabled = state.busy == null,
                                    onClick = { onAction(UpdatesAction.OnUpdateList(list.datasetKey)) },
                                )
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.padding(bottom = 24.dp))
        }
    }
}

@Composable
private fun Section(title: String, status: String) {
    Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 8.dp)) {
        Text(text = title, style = MaterialTheme.typography.titleMedium)
        Text(
            text = status,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Settled(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 16.dp),
    )
}

@Composable
private fun ActionButton(label: String, busy: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled) {
        if (busy) {
            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
        } else {
            Text(label)
        }
    }
}

@Preview
@Composable
private fun UpdatesScreenPreview() {
    MaterialTheme {
        UpdatesScreen(
            state = UpdatesState(
                isLoading = false,
                forms = listOf(FormUpdateUi("Household Survey", 3)),
                lists = listOf(
                    ListUpdateUi(
                        datasetKey = "villages",
                        statusLine = "villages v8 — not downloaded",
                        costLine = "Update from v7 — only the rows that changed. " +
                            "The whole list is about 11.3 MB.",
                        partial = false,
                    ),
                    ListUpdateUi(
                        datasetKey = "health_facilities",
                        statusLine = "health_facilities v2 — 412 of 1,900 rows",
                        costLine = "Full download — about 240 KB.",
                        partial = true,
                    ),
                ),
                formsStatus = "Checked 2026-09-10 09:14",
                listsStatus = "Not checked yet",
            ),
            onAction = {},
        )
    }
}
