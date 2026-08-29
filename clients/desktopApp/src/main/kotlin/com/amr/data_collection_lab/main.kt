package com.amr.data_collection_lab

import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import com.dcp.core.sync.DatabaseDriverFactory

fun main() = application {
    Window(
        onCloseRequest = ::exitApplication,
        title = "DataCollectionLab",
    ) {
        App(DatabaseDriverFactory())
    }
}
