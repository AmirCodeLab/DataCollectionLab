package com.amr.data_collection_lab

import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.amr.data_collection_lab.collection.AppGraph
import com.amr.data_collection_lab.collection.CollectionRoot
import com.amr.data_collection_lab.collection.CollectionViewModel
import com.amr.data_collection_lab.collection.SubmissionListRoot
import com.amr.data_collection_lab.collection.SubmissionListViewModel
import com.dcp.core.sync.DatabaseDriverFactory

private sealed interface Route {
    data object Submissions : Route
    data class Collection(val submissionId: String) : Route
}

@Composable
fun App(driverFactory: DatabaseDriverFactory) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme(),
    ) {
        val graph = remember { AppGraph(driverFactory) }
        var route by remember { mutableStateOf<Route>(Route.Submissions) }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .safeDrawingPadding(),
        ) {
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
    }
}
