package com.amr.data_collection_lab.collection

import com.amr.data_collection_lab.defaultSyncBaseUrl
import com.amr.data_collection_lab.platformDeviceInfo
import com.dcp.core.sync.DatabaseDriverFactory
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.SyncClient
import com.dcp.core.sync.createSubmissionStore

/** Manual wiring for the app's few long-lived objects. Replaced by Koin when DI lands. */
class AppGraph(driverFactory: DatabaseDriverFactory) {
    val store: SubmissionStore = createSubmissionStore(driverFactory)
    val formCatalog: FormCatalog = FormCatalog()
    val syncClient: SyncClient =
        SyncClient(store, defaultSyncBaseUrl(), deviceInfo = platformDeviceInfo())
}
