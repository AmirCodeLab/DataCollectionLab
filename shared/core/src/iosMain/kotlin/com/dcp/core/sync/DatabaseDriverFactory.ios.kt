package com.dcp.core.sync

import app.cash.sqldelight.db.SqlDriver
import app.cash.sqldelight.driver.native.NativeSqliteDriver
import co.touchlab.sqliter.DatabaseConfiguration
import co.touchlab.sqliter.DatabaseFileContext
import co.touchlab.sqliter.JournalMode
import co.touchlab.sqliter.NO_VERSION_CHECK
import co.touchlab.sqliter.createDatabaseManager
import co.touchlab.sqliter.longForQuery
import co.touchlab.sqliter.withStatement
import com.dcp.core.db.DcpDatabase
import com.dcp.core.security.DatabaseKey
import com.dcp.core.security.LocalDatabaseGuard
import kotlinx.cinterop.ExperimentalForeignApi
import platform.Foundation.NSData
import platform.Foundation.NSFileHandle
import platform.Foundation.NSFileManager
import platform.Foundation.closeFile
import platform.Foundation.fileHandleForReadingAtPath
import platform.Foundation.readDataOfLength
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.usePinned
import platform.posix.memcpy

/**
 * iOS driver, encrypted with SQLCipher (encryption envelope §14).
 *
 * SQLiter — which SQLDelight's native driver sits on — already models the key:
 * [DatabaseConfiguration.Encryption] issues `PRAGMA key` on every connection it
 * opens, escaping the value into a SQL string literal, so passing `x'<hex>'`
 * arrives as SQLCipher's raw-key form (§14.2).
 *
 * **The cipher itself comes from the Xcode link line, not from here.**
 * Kotlin/Native resolves `sqlite3_*` against whatever the app links, and the
 * SDK's `libsqlite3` has no cipher — against it `PRAGMA key` is an unrecognised
 * pragma, which SQLite ignores without error, and the database is written in
 * the clear while every test still passes. `scripts/build_sqlcipher_ios.sh`
 * builds the replacement and `clients/iosApp/Configuration/Config.xcconfig`
 * links it. The check at the end of [createDriver] is what makes forgetting
 * that step fail loudly instead of silently (§14.5).
 */
@OptIn(ExperimentalForeignApi::class)
actual class DatabaseDriverFactory {

    actual fun createDriver(key: DatabaseKey): SqlDriver {
        val path = DatabaseFileContext.databasePath(DATABASE_NAME, null)
        encryptInPlaceIfCleartext(path, key)

        val driver = NativeSqliteDriver(
            schema = DcpDatabase.Schema,
            name = DATABASE_NAME,
            onConfiguration = { configuration ->
                configuration.copy(
                    encryptionConfig = DatabaseConfiguration.Encryption(
                        key = key.rawKeyLiteral(),
                    ),
                )
            },
        )

        // The driver opens lazily, so nothing is on disk until something is
        // asked of it. This is that ask, and the first moment the file can be
        // judged.
        driver.executeQuery(null, "SELECT 1", { app.cash.sqldelight.db.QueryResult.Unit }, 0)

        try {
            LocalDatabaseGuard.requireEncrypted(path, fileHeader(path))
        } catch (e: Throwable) {
            driver.close()
            throw e
        }
        return driver
    }

    actual fun databaseState(): LocalDatabaseState {
        val path = DatabaseFileContext.databasePath(DATABASE_NAME, null)
        val header = fileHeader(path) ?: return LocalDatabaseState.ABSENT
        return if (LocalDatabaseGuard.isCleartext(header)) {
            LocalDatabaseState.CLEARTEXT
        } else {
            LocalDatabaseState.ENCRYPTED
        }
    }

    /**
     * Upgrades a database written by a build that predates §14.
     *
     * Migrated, never recreated: the device's logical counter lives in this
     * file and operation nonces are derived from it (§4.5), so a device that
     * started a fresh database and later encrypted would reuse a nonce.
     *
     * [NO_VERSION_CHECK] keeps SQLiter from running the schema's create or
     * upgrade callbacks against the cleartext file on the way past — this
     * connection exists only to copy the data out.
     */
    private fun encryptInPlaceIfCleartext(path: String, key: DatabaseKey) {
        val files = NSFileManager.defaultManager()
        if (!files.fileExistsAtPath(path)) return
        if (!LocalDatabaseGuard.isCleartext(fileHeader(path))) return

        val workingName = "$DATABASE_NAME.migrating"
        val workingPath = DatabaseFileContext.databasePath(workingName, null)
        files.removeItemAtPath(workingPath, null)

        val plain = createDatabaseManager(
            DatabaseConfiguration(
                name = DATABASE_NAME,
                version = NO_VERSION_CHECK,
                create = {},
                journalMode = JournalMode.DELETE,
            ),
        ).createMultiThreadedConnection()

        try {
            // Committed pages can still be sitting in a -wal left by the
            // previous build; without this the export copies a database missing
            // its most recent answers.
            plain.rawExecSql("PRAGMA wal_checkpoint(TRUNCATE)")
            val userVersion = plain.longForQuery("PRAGMA user_version")

            // Bound parameters, not interpolated text, and not for tidiness:
            // SQLite's error log prints the SQL of a statement that fails, so
            // interpolating would put the key hex into the device log the first
            // time an ATTACH went wrong. It did exactly that on Android before
            // this was fixed. (§14.5 — never log the key.)
            plain.withStatement("ATTACH DATABASE ? AS encrypted KEY ?") {
                bindString(1, workingPath)
                bindString(2, key.rawKeyLiteral())
                execute()
            }
            plain.rawExecSql("SELECT sqlcipher_export('encrypted')")
            // sqlcipher_export copies schema and rows and not this pragma.
            // SQLDelight reads it to decide which .sqm migrations to run, so
            // losing it makes the next launch replay every migration against a
            // schema that already has them.
            plain.rawExecSql("PRAGMA encrypted.user_version = $userVersion")
            plain.rawExecSql("DETACH DATABASE encrypted")
        } finally {
            plain.close()
        }

        check(!LocalDatabaseGuard.isCleartext(fileHeader(workingPath))) {
            "sqlcipher_export left $workingName readable without a key; refusing to install it"
        }

        files.removeItemAtPath(path, null)
        check(files.moveItemAtPath(workingPath, toPath = path, error = null)) {
            "could not install the encrypted database over $DATABASE_NAME"
        }
        // Journals belonging to the cleartext file. Left behind they are
        // plaintext pages beside an encrypted database, and SQLite would try to
        // replay them into it.
        files.removeItemAtPath("$path-wal", null)
        files.removeItemAtPath("$path-shm", null)
        files.removeItemAtPath("$path-journal", null)
        // Deleting does not erase the blocks — §14.6 says so plainly rather
        // than implying the plaintext is gone. Only a factory reset closes that.
    }

    private companion object {
        const val DATABASE_NAME = "dcp.db"

        fun fileHeader(path: String): ByteArray? {
            val handle = NSFileHandle.fileHandleForReadingAtPath(path) ?: return null
            val data: NSData = try {
                handle.readDataOfLength(LocalDatabaseGuard.CLEARTEXT_HEADER.size.toULong())
            } finally {
                handle.closeFile()
            }
            val size = data.length.toInt()
            if (size < LocalDatabaseGuard.CLEARTEXT_HEADER.size) return null
            val out = ByteArray(size)
            out.usePinned { memcpy(it.addressOf(0), data.bytes, data.length) }
            return out
        }
    }
}
