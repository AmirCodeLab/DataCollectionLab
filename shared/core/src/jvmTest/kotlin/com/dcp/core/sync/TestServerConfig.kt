package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.util.Properties

/**
 * A [ServerConfig] pinned to one address, for tests that do not care about
 * configuring one.
 *
 * `SyncClient` and `MediaUploader` take a `ServerConfig` rather than a `String`
 * or a `() -> String` on purpose: the lambda was exactly wide enough to express
 * the mistake it existed to prevent, and the app's own wiring made it — the
 * settings screen reported an address saved while the sync went to the
 * compile-time constant, with all 264 tests green (break 35).
 *
 * The cost of closing that hole is that a test needs a `ServerConfig`, and a
 * `ServerConfig` needs somewhere to keep a row. This gives it a throwaway
 * in-memory database and never writes to it, so [ServerConfig.baseUrl] answers
 * with the platform default it was handed and nothing else.
 *
 * **This lives in the test source set, and that is what makes it safe.**
 * Production code cannot reach it, so the only `ServerConfig` the app can hand
 * a client is the real one.
 */
internal fun fixedServerConfig(url: String): ServerConfig =
    ServerConfig(
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)),
        url,
    )
