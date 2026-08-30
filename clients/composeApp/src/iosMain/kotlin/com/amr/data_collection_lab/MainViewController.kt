package com.amr.data_collection_lab

import androidx.compose.ui.window.ComposeUIViewController
import com.amr.data_collection_lab.collection.MediaPlatform
import com.dcp.core.media.LocationProvider
import com.dcp.core.media.MediaFileStore
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory

fun MainViewController() = ComposeUIViewController {
    App(
        driverFactory = DatabaseDriverFactory(),
        // The key lives in the Keychain, WhenUnlockedThisDeviceOnly
        // (encryption envelope §14.4). With the app lock on, iOS itself raises
        // the Face ID / passcode prompt when the item is read.
        keyStore = DatabaseKeyStore(requireUserPresence = AppLock.ENABLED),
        // Media capture (encryption envelope §6). Ciphertext chunks go under
        // Documents, excluded from iCloud backup; the per-file keys that open
        // them live in the SQLCipher database above.
        mediaPlatform = MediaPlatform(
            files = MediaFileStore(),
            location = LocationProvider(),
        ),
    )
}
