package com.dcp.core.sync

import android.content.Context
import androidx.sqlite.db.SupportSQLiteOpenHelper
import app.cash.sqldelight.db.SqlDriver
import app.cash.sqldelight.driver.android.AndroidSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.core.security.DatabaseKey
import com.dcp.core.security.LocalDatabaseGuard
import java.io.File
import net.zetetic.database.sqlcipher.SQLiteDatabase
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory

/**
 * Android driver, encrypted with SQLCipher (encryption envelope §14).
 *
 * Zetetic's `sqlcipher-android` ships a `SupportSQLiteOpenHelper.Factory`, so
 * the whole cipher fits into the one constructor argument SQLDelight already
 * takes — the queries above it are untouched and cannot tell the difference.
 */
actual class DatabaseDriverFactory(private val context: Context) {

    actual fun createDriver(key: DatabaseKey): SqlDriver {
        loadSqlCipher()

        val file = context.getDatabasePath(DATABASE_NAME)
        encryptInPlaceIfCleartext(file, key)

        // The bytes of the string x'<hex>', not the 32 raw bytes. SQLCipher
        // reads that literal and uses the key directly; handed the raw bytes it
        // would treat them as a password and grind 256,000 PBKDF2 iterations
        // over material that is already full-entropy (§14.2) — a visible pause
        // at every launch on exactly the cheap hardware this app targets.
        //
        // The factory zeroes this array once it has keyed the database, which
        // is why it gets a fresh one rather than anything we keep.
        val factory = SupportOpenHelperFactory(key.rawKeyLiteral().toByteArray(Charsets.UTF_8))

        val helper = factory.create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name(DATABASE_NAME)
                .callback(AndroidSqliteDriver.Callback(DcpDatabase.Schema))
                .build(),
        )

        // Opened here rather than left to the driver's first query: it is the
        // point where the schema is created or migrated, so it is the earliest
        // moment the file on disk can be judged — and if the answer is "this is
        // cleartext", nothing must have been written into it yet.
        helper.writableDatabase

        try {
            LocalDatabaseGuard.requireEncrypted(file.absolutePath, fileHeader(file))
        } catch (e: Throwable) {
            helper.close()
            throw e
        }
        return AndroidSqliteDriver(helper)
    }

    actual fun databaseState(): LocalDatabaseState {
        val file = context.getDatabasePath(DATABASE_NAME)
        if (!file.isFile || file.length() == 0L) return LocalDatabaseState.ABSENT
        return if (LocalDatabaseGuard.isCleartext(fileHeader(file))) {
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
     * `sqlcipher_export` writes into a new file and the old one is deleted only
     * after the new one has been reopened under the key and read. A crash
     * before that leaves the cleartext database untouched and openable.
     */
    private fun encryptInPlaceIfCleartext(file: File, key: DatabaseKey) {
        if (!file.exists() || !LocalDatabaseGuard.isCleartext(fileHeader(file))) return

        val working = File(file.parentFile, file.name + ".migrating")
        working.delete()

        // An empty passphrase means "do not key this connection", which is how
        // SQLCipher opens a plain database — and the only way to run
        // sqlcipher_export, which has to be called from the cleartext side.
        //
        // CREATE_IF_NECESSARY is not about this file, which certainly exists.
        // SQLite reuses the main connection's open flags for every database
        // ATTACHed to it, so without it the ATTACH below cannot create the
        // encrypted target and fails with SQLITE_CANTOPEN — which is exactly
        // what it did on a real device the first time this ran.
        val source = SQLiteDatabase.openDatabase(
            file.absolutePath,
            "",
            null,
            SQLiteDatabase.OPEN_READWRITE or SQLiteDatabase.CREATE_IF_NECESSARY,
            null,
        )
        try {
            // Committed pages can still be sitting in the -wal; without this
            // the export copies a database missing its most recent answers.
            source.rawExecSQL("PRAGMA wal_checkpoint(TRUNCATE)")
            val userVersion = source.version

            // Bound parameters, not interpolated text, and not for tidiness:
            // SQLite's error log prints the SQL of a statement that fails, and
            // the first version of this line put the key hex into logcat when
            // the ATTACH failed. With binds the log shows the `?`. (§14.5 —
            // never log the key.)
            source.rawExecSQL(
                "ATTACH DATABASE ? AS encrypted KEY ?",
                working.absolutePath,
                key.rawKeyLiteral(),
            )
            source.rawExecSQL("SELECT sqlcipher_export('encrypted')")
            // sqlcipher_export copies schema and rows and not this pragma.
            // SQLDelight reads it to decide which .sqm migrations to run, so
            // losing it makes the next launch replay every migration against a
            // schema that already has them.
            source.rawExecSQL("PRAGMA encrypted.user_version = $userVersion")
            source.rawExecSQL("DETACH DATABASE encrypted")
        } finally {
            source.close()
        }

        // Prove the copy before destroying the only readable original.
        SQLiteDatabase.openDatabase(
            working.absolutePath, key.rawKeyLiteral(), null, SQLiteDatabase.OPEN_READONLY, null,
        ).use { database ->
            database.query("SELECT count(*) FROM sqlite_master").use { it.moveToFirst() }
        }
        check(!LocalDatabaseGuard.isCleartext(fileHeader(working))) {
            "sqlcipher_export left ${working.name} readable without a key; refusing to install it"
        }

        check(working.renameTo(file)) { "could not install the encrypted database over ${file.name}" }
        // Journals belonging to the cleartext file. Left behind they are
        // plaintext pages beside an encrypted database, and SQLite would try to
        // replay them into it.
        File(file.parentFile, file.name + "-wal").delete()
        File(file.parentFile, file.name + "-shm").delete()
        File(file.parentFile, file.name + "-journal").delete()
        // Deleting does not erase the blocks — §14.6 says so plainly rather
        // than implying the plaintext is gone. Only a factory reset closes that.
    }

    private companion object {
        const val DATABASE_NAME = "dcp.db"

        /**
         * `sqlcipher-android` — unlike the older `android-database-sqlcipher` —
         * has no `loadLibs(Context)`; the caller loads the .so. Guarded so a
         * second driver in the same process does not reload it.
         */
        @Volatile
        var libraryLoaded = false

        @Synchronized
        fun loadSqlCipher() {
            if (libraryLoaded) return
            System.loadLibrary("sqlcipher")
            libraryLoaded = true
        }

        fun fileHeader(file: File): ByteArray? {
            if (!file.isFile) return null
            return file.inputStream().use { stream ->
                val header = ByteArray(LocalDatabaseGuard.CLEARTEXT_HEADER.size)
                var read = 0
                while (read < header.size) {
                    val n = stream.read(header, read, header.size - read)
                    if (n < 0) return null
                    read += n
                }
                header
            }
        }
    }
}
