package com.amr.data_collection_lab

import com.dcp.core.sync.DeviceInfo

/** Where the sync API lives for a dev build. Becomes server-configurable
 * once device enrollment exists. */
expect fun defaultSyncBaseUrl(): String

/** Reported to POST /api/v1/devices on first sync (sync §4). */
expect fun platformDeviceInfo(): DeviceInfo

// Until versioning is wired through the build, one hand-maintained constant
// shared by every platform actual.
internal const val APP_VERSION: String = "0.1.0-dev"
