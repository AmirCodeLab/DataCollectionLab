package com.amr.data_collection_lab

/** Today's date in the device's local timezone, as `YYYY-MM-DD`. Feeds the form
 * engine's `today()` and date constraints. */
expect fun todayIsoDate(): String
