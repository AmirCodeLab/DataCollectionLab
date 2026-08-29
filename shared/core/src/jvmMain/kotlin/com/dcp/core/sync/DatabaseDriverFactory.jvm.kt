package com.dcp.core.sync

import app.cash.sqldelight.db.SqlDriver
import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.io.File
import java.util.Properties

actual class DatabaseDriverFactory(
    private val path: String = defaultPath(),
) {
    actual fun createDriver(): SqlDriver =
        JdbcSqliteDriver("jdbc:sqlite:$path", Properties(), DcpDatabase.Schema)

    companion object {
        fun defaultPath(): String {
            val dir = File(System.getProperty("user.home"), ".dcp")
            dir.mkdirs()
            return File(dir, "dcp.db").absolutePath
        }
    }
}
