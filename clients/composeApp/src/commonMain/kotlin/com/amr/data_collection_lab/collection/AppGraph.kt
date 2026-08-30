package com.amr.data_collection_lab.collection

import com.amr.data_collection_lab.defaultSyncBaseUrl
import com.amr.data_collection_lab.platformDeviceInfo
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory
import com.dcp.core.sync.FormSensitivity
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.SyncClient
import com.dcp.core.sync.createSubmissionStore
import com.dcp.form.sensitiveFields

/**
 * Manual wiring for the app's few long-lived objects. Replaced by Koin when DI
 * lands.
 *
 * Constructing this opens the local database, which means reading the database
 * key out of the platform keystore (encryption envelope §14). It throws rather
 * than degrading if that fails — see [com.amr.data_collection_lab.App], which
 * turns the throw into a screen that says what went wrong.
 */
class AppGraph(driverFactory: DatabaseDriverFactory, keyStore: DatabaseKeyStore) {
    val store: SubmissionStore = createSubmissionStore(driverFactory, keyStore)
    val formCatalog: FormCatalog = FormCatalog()

    /**
     * What `field_level` encryption acts on (Form IR §2.1). Answering null for
     * a form version this device has not compiled makes the sync path fail
     * closed and encrypt the value rather than assume it is safe to send in the
     * clear.
     */
    private val formSensitivity = FormSensitivity { formId, formVersion ->
        formCatalog.compiledForm()
            .takeIf { it.formId == formId && it.version == formVersion }
            ?.sensitiveFields()
    }

    val syncClient: SyncClient = SyncClient(
        store,
        defaultSyncBaseUrl(),
        deviceInfo = platformDeviceInfo(),
        formSensitivity = formSensitivity,
    )
}
