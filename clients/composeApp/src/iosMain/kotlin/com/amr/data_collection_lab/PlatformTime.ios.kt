package com.amr.data_collection_lab

import platform.Foundation.NSDate
import platform.Foundation.NSDateFormatter
import platform.Foundation.NSLocale

actual fun todayIsoDate(): String {
    val formatter = NSDateFormatter()
    formatter.dateFormat = "yyyy-MM-dd"
    formatter.locale = NSLocale("en_US_POSIX")
    return formatter.stringFromDate(NSDate())
}
