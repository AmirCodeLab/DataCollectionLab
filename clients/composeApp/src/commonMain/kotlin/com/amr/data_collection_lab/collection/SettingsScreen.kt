package com.amr.data_collection_lab.collection

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardOptions
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun SettingsRoot(
    viewModel: SettingsViewModel,
    onNavigateBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    ObserveAsEvents(viewModel.events) { event ->
        when (event) {
            SettingsEvent.NavigateBack -> onNavigateBack()
        }
    }

    SettingsScreen(state = state, onAction = viewModel::onAction)
}

/**
 * Three sections, in the order somebody debugging a phone asks about them:
 * where is the server, did the last sync work, and what is actually on here.
 *
 * The strings are English, like the rest of the app chrome. `UiStrings` is for
 * the *form* language — a field team shares devices and picks a language per
 * interview — and this screen is not part of an interview.
 */
@Composable
fun SettingsScreen(
    state: SettingsState,
    onAction: (SettingsAction) -> Unit,
) {
    Scaffold(contentWindowInsets = WindowInsets(0.dp)) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { onAction(SettingsAction.OnBack) }) { Text("Back") }
                Spacer(Modifier.width(8.dp))
                Text("Settings", style = MaterialTheme.typography.headlineSmall)
            }

            Spacer(Modifier.height(16.dp))
            ServerSection(state, onAction)

            Spacer(Modifier.height(24.dp))
            HorizontalDivider()
            Spacer(Modifier.height(16.dp))
            SyncSection(state)

            Spacer(Modifier.height(24.dp))
            HorizontalDivider()
            Spacer(Modifier.height(16.dp))
            FormsSection(state)

            Spacer(Modifier.height(24.dp))
            HorizontalDivider()
            Spacer(Modifier.height(16.dp))
            // Last, and small. It is never the answer, but it is the first
            // thing a server-side person asks for, and reading it off a screen
            // beats not being able to find it at all.
            Text("Device", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                text = state.deviceId,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ServerSection(state: SettingsState, onAction: (SettingsAction) -> Unit) {
    Text("Server", style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(8.dp))

    OutlinedTextField(
        value = state.serverUrlDraft,
        onValueChange = { onAction(SettingsAction.OnServerUrlChanged(it)) },
        label = { Text("Server address") },
        placeholder = { Text("http://192.168.1.20:8000") },
        singleLine = true,
        isError = state.urlError != null,
        // Uri, not Text: it suppresses autocapitalisation and autocorrect,
        // both of which quietly mangle a hostname typed on a phone.
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Uri,
            imeAction = ImeAction.Done,
        ),
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "Server address" },
    )

    when {
        state.urlError != null -> Text(
            text = state.urlError,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.padding(top = 4.dp),
        )

        state.savedNotice != null -> Text(
            text = state.savedNotice,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.padding(top = 4.dp),
        )

        state.isPlatformDefault -> Text(
            // Saying which address is in use and that nobody chose it. A phone
            // that has never been configured looks exactly like one that has,
            // and this is the line that tells them apart.
            text = "Using this build's default address. No address has been set on this device.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )
    }

    Spacer(Modifier.height(12.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Button(
            onClick = { onAction(SettingsAction.OnSaveServerUrl) },
            enabled = state.canSave,
        ) { Text("Save") }

        Spacer(Modifier.width(8.dp))
        Button(
            onClick = { onAction(SettingsAction.OnTestConnection) },
            enabled = !state.isTestingConnection,
        ) {
            if (state.isTestingConnection) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
            } else {
                Text("Test connection")
            }
        }

        if (!state.isPlatformDefault) {
            Spacer(Modifier.width(8.dp))
            TextButton(onClick = { onAction(SettingsAction.OnResetToDefault) }) {
                Text("Reset")
            }
        }
    }

    state.connection?.let { result ->
        Spacer(Modifier.height(8.dp))
        when (result) {
            is ConnectionUi.Reached -> Text(
                // The environment, not just a tick. A phone that reaches
                // staging when it should reach production connects perfectly
                // and files a morning's interviews where nobody will look.
                text = "Reached ${result.url} — this is the ${result.environment} server.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )

            is ConnectionUi.Failed -> Text(
                text = result.reason,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
private fun SyncSection(state: SettingsState) {
    Text("Last sync", style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(8.dp))

    Text(
        text = state.lastSyncAt?.let { "Last successful sync $it" }
            // "Never" and "failed" are different situations with different next
            // steps, and a blank timestamp says neither.
            ?: "This device has never completed a sync.",
        style = MaterialTheme.typography.bodyMedium,
    )
    Text(
        text = if (state.pendingOps == 0L) "Nothing waiting to sync"
        else "${state.pendingOps} ops waiting to sync",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    state.lastSyncError?.let {
        Spacer(Modifier.height(4.dp))
        Text(
            // Already a sentence naming the address and a likely cause — see
            // SyncFailure. Rendered whole rather than trimmed, because the
            // part usually cut is the platform's original message, which is
            // the only part that is a fact rather than a guess.
            text = it,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun FormsSection(state: SettingsState) {
    Text("Forms on this device", style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(8.dp))

    if (state.forms.isEmpty()) {
        Text(
            text = if (state.lastSyncAt == null) {
                "None yet. Forms arrive on the first successful sync."
            } else {
                // Synced, and still nothing. That is a server-side answer —
                // published is not deployed — and sending someone back to
                // press Sync again would waste their time.
                "None. This device has synced, so its project has no form " +
                    "deployed to this device's environment."
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        state.forms.forEach { form ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(form.title, style = MaterialTheme.typography.bodyLarge)
                    Text(
                        text = "${form.formId} · v${form.version} · fetched ${form.fetchedAt}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (!form.deployed) {
                    Spacer(Modifier.width(8.dp))
                    // A version the server has stopped deploying, still here
                    // because a submission refers to it (Form IR §9). Without
                    // this chip it is indistinguishable from a current form,
                    // and it is the one a supervisor is ringing about.
                    SuggestionChip(onClick = {}, label = { Text("Withdrawn") })
                }
            }
        }
    }
}

@Preview
@Composable
private fun SettingsScreenPreview() {
    MaterialTheme {
        SettingsScreen(
            state = SettingsState(
                serverUrlDraft = "http://192.168.1.20:8000",
                serverUrlInEffect = "http://192.168.1.20:8000",
                isPlatformDefault = false,
                platformDefault = "http://10.0.2.2:8000",
                deviceId = "dev_9f2c81ab",
                lastSyncAt = "2026-09-02 09:14",
                pendingOps = 12,
                connection = ConnectionUi.Reached("http://192.168.1.20:8000", "production"),
                forms = listOf(
                    HeldFormUi("Household Survey", "household_survey", 2, true, "2026-09-02 09:14"),
                    HeldFormUi("Household Survey", "household_survey", 1, false, "2026-08-28 11:02"),
                ),
                isLoading = false,
            ),
            onAction = {},
        )
    }
}

@Preview
@Composable
private fun SettingsScreenUnconfiguredPreview() {
    MaterialTheme {
        SettingsScreen(
            state = SettingsState(
                serverUrlDraft = "http://10.0.2.2:8000",
                serverUrlInEffect = "http://10.0.2.2:8000",
                isPlatformDefault = true,
                platformDefault = "http://10.0.2.2:8000",
                deviceId = "dev_9f2c81ab",
                connection = ConnectionUi.Failed(
                    "http://10.0.2.2:8000",
                    "Nothing is listening at http://10.0.2.2:8000. The address was reached, " +
                        "so this is usually the server not running, or running on a different " +
                        "port. Note: 10.0.2.2 only works in the Android emulator.",
                ),
                isLoading = false,
            ),
            onAction = {},
        )
    }
}
