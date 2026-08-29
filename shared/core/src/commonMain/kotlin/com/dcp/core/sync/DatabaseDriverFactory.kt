package com.dcp.core.sync

import app.cash.sqldelight.db.SqlDriver

/**
 * Platform SQLite driver for [com.dcp.core.db.DcpDatabase]. Constructed by each
 * launcher (the Android one needs a Context) and handed to shared code.
 */
expect class DatabaseDriverFactory {
    fun createDriver(): SqlDriver
}
