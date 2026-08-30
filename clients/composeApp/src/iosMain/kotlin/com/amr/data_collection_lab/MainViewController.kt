package com.amr.data_collection_lab

import androidx.compose.ui.window.ComposeUIViewController
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory

fun MainViewController() = ComposeUIViewController {
    App(
        driverFactory = DatabaseDriverFactory(),
        // The key lives in the Keychain, WhenUnlockedThisDeviceOnly
        // (encryption envelope §14.4). With the app lock on, iOS itself raises
        // the Face ID / passcode prompt when the item is read.
        keyStore = DatabaseKeyStore(requireUserPresence = AppLock.ENABLED),
    )
}
