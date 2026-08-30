package com.amr.data_collection_lab

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.amr.data_collection_lab.collection.MediaPlatform
import com.dcp.core.media.LocationProvider
import com.dcp.core.media.MediaFileStore
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        setContent {
            App(
                driverFactory = DatabaseDriverFactory(applicationContext),
                // The local database key, derived inside the Android Keystore
                // (encryption envelope §14.4). The app lock of §14.7 is off by
                // default: it is a property of the keystore key, so it has to
                // be chosen before the key exists — see AppLock.
                keyStore = DatabaseKeyStore(requireUserAuthentication = AppLock.ENABLED),
                // Media capture (encryption envelope §6). The file store writes
                // ciphertext chunks into app-private internal storage; the
                // per-file keys that open them live in the SQLCipher database
                // above, so a photograph of an ID card is never on this disk in
                // the clear.
                mediaPlatform = MediaPlatform(
                    files = MediaFileStore(applicationContext),
                    location = LocationProvider(applicationContext),
                ),
            )
        }
    }
}
