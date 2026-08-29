package com.amr.data_collection_lab

import com.dcp.core.sync.DeviceInfo

actual fun defaultSyncBaseUrl(): String = "http://localhost:8000"

actual fun platformDeviceInfo(): DeviceInfo = DeviceInfo(
    platform = "desktop",
    osVersion = "${System.getProperty("os.name")} ${System.getProperty("os.version")}",
    appVersion = APP_VERSION,
)
