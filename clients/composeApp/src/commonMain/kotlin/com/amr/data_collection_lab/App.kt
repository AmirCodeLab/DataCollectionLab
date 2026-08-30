package com.amr.data_collection_lab

import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.amr.data_collection_lab.collection.AppGraph
import com.amr.data_collection_lab.collection.CollectionRoot
import com.amr.data_collection_lab.collection.CollectionViewModel
import com.amr.data_collection_lab.collection.SubmissionListRoot
import com.amr.data_collection_lab.collection.SubmissionListViewModel
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.security.DatabaseKeyUnavailable
import com.dcp.core.security.LocalDatabaseNotEncrypted
import com.dcp.core.sync.DatabaseDriverFactory

private sealed interface Route {
    data object Submissions : Route
    data class Collection(val submissionId: String) : Route
}

@Composable
fun App(driverFactory: DatabaseDriverFactory, keyStore: DatabaseKeyStore) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme(),
    ) {
        // Opening the local database means getting its key out of the platform
        // keystore, and encryption envelope §14.5 forbids a fallback: if the
        // key is not available there is no database, and the app has to say so
        // rather than start empty. Starting empty is the dangerous outcome —
        // the enumerator sees no submissions and concludes the work is gone.
        val graph = remember { runCatching { AppGraph(driverFactory, keyStore) } }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .safeDrawingPadding(),
        ) {
            graph.fold(
                onFailure = { LocalDatabaseUnavailable(it) },
                onSuccess = { Collection(it) },
            )
        }
    }
}

@Composable
private fun Collection(graph: AppGraph) {
    var route by remember { mutableStateOf<Route>(Route.Submissions) }
    when (val current = route) {
        Route.Submissions -> SubmissionListRoot(
            viewModel = viewModel {
                SubmissionListViewModel(graph.store, graph.formCatalog, graph.syncClient)
            },
            onNavigateToCollection = { route = Route.Collection(it) },
        )
        is Route.Collection -> CollectionRoot(
            viewModel = viewModel(key = "collection_${current.submissionId}") {
                CollectionViewModel(graph.store, graph.formCatalog, current.submissionId)
            },
            onNavigateBack = { route = Route.Submissions },
        )
    }
}

/**
 * The screen for the one thing §14.5 says must not be worked around.
 *
 * There is nothing to offer but an explanation. A "continue without
 * encryption" button is the whole hole this section closes, and a retry button
 * would be a lie for every cause but a missed app-lock prompt — so the message
 * distinguishes them and the app stops.
 */
@Composable
private fun LocalDatabaseUnavailable(cause: Throwable) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = when (cause) {
                is LocalDatabaseNotEncrypted -> "This build cannot encrypt its local storage"
                is DatabaseKeyUnavailable -> "This device's data is locked"
                else -> "The local database could not be opened"
            },
            style = MaterialTheme.typography.headlineSmall,
        )
        Spacer(Modifier.height(12.dp))
        Text(
            text = when (cause) {
                is LocalDatabaseNotEncrypted ->
                    "Answers on this device would be stored unprotected, so the app has " +
                        "stopped. Report this build — it is a packaging fault, not a device " +
                        "fault, and reinstalling will not fix it."

                is DatabaseKeyUnavailable ->
                    "The key that unlocks this device's answers is held by the operating " +
                        "system and it did not release it. Unlock the device and open the app " +
                        "again. No data has been lost or changed."

                else -> "The app has stopped rather than start with an empty database."
            },
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(16.dp))
        // The underlying message, for a supervisor reading it down a phone line.
        Text(
            text = cause.message ?: cause::class.simpleName.orEmpty(),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
