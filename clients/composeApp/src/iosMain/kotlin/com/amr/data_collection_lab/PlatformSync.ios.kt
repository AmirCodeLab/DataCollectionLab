package com.amr.data_collection_lab

import com.dcp.core.sync.DeviceInfo
import platform.UIKit.UIDevice

// Simulator shares the host's loopback. ATS must allow plain http for this
// dev URL before iOS sync is exercised.
actual fun defaultSyncBaseUrl(): String = "http://localhost:8000"

actual fun platformDeviceInfo(): DeviceInfo = DeviceInfo(
    platform = "ios",
    osVersion = "${UIDevice.currentDevice.systemName} ${UIDevice.currentDevice.systemVersion}",
    appVersion = APP_VERSION,
)
