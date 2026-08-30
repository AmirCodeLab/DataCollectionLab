package com.amr.data_collection_lab

import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory

fun main() = application {
    Window(
        onCloseRequest = ::exitApplication,
        title = "DataCollectionLab",
    ) {
        // The key comes from the OS credential store — macOS Keychain,
        // Windows Credential Manager, Linux Secret Service (envelope §14.4).
        // That store's own unlock is the desktop app lock; there is nothing to
        // switch on here.
        App(DatabaseDriverFactory(), DatabaseKeyStore())
    }
}
