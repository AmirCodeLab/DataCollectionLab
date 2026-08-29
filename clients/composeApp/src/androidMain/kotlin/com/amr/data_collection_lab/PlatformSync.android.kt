package com.amr.data_collection_lab

import android.os.Build
import com.dcp.core.sync.DeviceInfo

// 10.0.2.2 is the emulator's alias for the host machine. A physical device
// needs the host's LAN address instead.
actual fun defaultSyncBaseUrl(): String = "http://10.0.2.2:8000"

actual fun platformDeviceInfo(): DeviceInfo = DeviceInfo(
    platform = "android",
    osVersion = "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
    appVersion = APP_VERSION,
)
