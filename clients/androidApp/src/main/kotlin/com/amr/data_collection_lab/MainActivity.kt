package com.amr.data_collection_lab

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
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
            )
        }
    }
}
