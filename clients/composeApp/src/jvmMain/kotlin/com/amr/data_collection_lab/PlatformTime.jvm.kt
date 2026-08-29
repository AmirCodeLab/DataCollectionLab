package com.amr.data_collection_lab

import java.time.LocalDate

actual fun todayIsoDate(): String = LocalDate.now().toString()
