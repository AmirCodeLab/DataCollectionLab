package com.dcp.core.sync

import app.cash.sqldelight.db.SqlDriver
import com.dcp.core.security.DatabaseKey

/**
 * Platform SQLite driver for [com.dcp.core.db.DcpDatabase]. Constructed by each
 * launcher (the Android one needs a Context) and handed to shared code.
 *
 * Every implementation opens the database through SQLCipher under [key]
 * (encryption envelope §14) and every one of them verifies afterwards that what
 * landed on disk is not a cleartext SQLite file — an unrecognised `PRAGMA key`
 * is a silent no-op, so calling it is not the same as being encrypted (§14.5).
 *
 * There is no key-less overload, and adding one would defeat the point: the
 * type system is the cheapest place to make "open the database" and "have the
 * key" the same act.
 */
expect class DatabaseDriverFactory {

    /**
     * @throws com.dcp.core.security.LocalDatabaseNotEncrypted if the build is
     *   linked against plain SQLite and the database was written in the clear.
     */
    fun createDriver(key: DatabaseKey): SqlDriver

    /** What is on disk before anything opens it. See [LocalDatabaseState]. */
    fun databaseState(): LocalDatabaseState
}

/**
 * What the local database file looks like before a driver touches it.
 *
 * Read once at startup to catch the one combination that destroys data
 * silently: an [ENCRYPTED] database and a keystore that says there is no key.
 * That pairing means the key was lost, not that this is a first run — and
 * generating a fresh key on top of it makes every unsynced answer on the device
 * permanently unreadable (encryption envelope §14.3) while the app looks
 * perfectly healthy.
 *
 * It has to be a distinct check because the platform keystores cannot always
 * tell "no such item" from "I will not answer you". macOS's `security(1)`, for
 * one, reports both as `errSecItemNotFound`.
 */
enum class LocalDatabaseState {
    /** No database yet — a genuine first run. */
    ABSENT,

    /** A database from a build that predates §14; it will be migrated. */
    CLEARTEXT,

    /** An encrypted database, which is worthless without the key that made it. */
    ENCRYPTED,
}
