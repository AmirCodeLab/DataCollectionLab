package com.amr.data_collection_lab

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// SimpleDateFormat, not java.time: minSdk is 24 and java.time needs API 26.
actual fun todayIsoDate(): String =
    SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
