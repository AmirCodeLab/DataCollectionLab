package com.dcp.core.sync

import app.cash.sqldelight.db.SqlDriver
import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.core.security.DatabaseKey
import com.dcp.core.security.LocalDatabaseGuard
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.sql.DriverManager
import java.util.Properties
import org.sqlite.mc.SQLiteMCSqlCipherConfig

/**
 * Desktop driver, encrypted with SQLCipher (encryption envelope §14).
 *
 * The cipher comes from SQLite3 Multiple Ciphers — `io.github.willena:sqlite-jdbc`,
 * a fork of `org.xerial:sqlite-jdbc` with the SQLCipher codec compiled into the
 * bundled native library. It is substituted for the stock driver in
 * `shared/core/build.gradle.kts`, because both on the classpath means two
 * `org.sqlite.JDBC` registrations and whichever wins is a coin toss — and the
 * one that loses silently is the one that encrypts.
 */
actual class DatabaseDriverFactory(
    private val path: String = defaultPath(),
) {

    actual fun createDriver(key: DatabaseKey): SqlDriver {
        val file = File(path)
        encryptInPlaceIfCleartext(file, key)

        val driver = JdbcSqliteDriver("jdbc:sqlite:$path", keyProperties(key), DcpDatabase.Schema)

        // After the driver, not before: JdbcSqliteDriver creates and migrates
        // the schema in its constructor, so this is the first moment there are
        // bytes on disk to judge. If SQLCipher were missing they would be
        // cleartext ones, and nothing else in the process would say so.
        try {
            LocalDatabaseGuard.requireEncrypted(path, fileHeader(file))
        } catch (e: Throwable) {
            driver.close()
            throw e
        }
        return driver
    }

    actual fun databaseState(): LocalDatabaseState {
        val file = File(path)
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
     * The rekey runs against a copy and the copy is moved over the original
     * only once it has been reopened and read back under the new key. A crash
     * at any point before that leaves the untouched cleartext database in
     * place — recoverable — rather than a half-rewritten one, which is not.
     */
    private fun encryptInPlaceIfCleartext(file: File, key: DatabaseKey) {
        if (!file.exists() || !LocalDatabaseGuard.isCleartext(fileHeader(file))) return

        val working = File(file.parentFile, file.name + ".migrating")
        working.delete()

        // A -wal alongside the source holds committed pages that are not in the
        // main file yet. Checkpointing folds them in, so the copy is complete.
        DriverManager.getConnection("jdbc:sqlite:${file.absolutePath}").use { source ->
            source.createStatement().use { it.execute("PRAGMA wal_checkpoint(TRUNCATE)") }
        }
        Files.copy(file.toPath(), working.toPath(), StandardCopyOption.REPLACE_EXISTING)

        DriverManager.getConnection("jdbc:sqlite:${working.absolutePath}").use { connection ->
            connection.createStatement().use { statement ->
                // Without this the rekey uses SQLite3MC's default cipher
                // (ChaCha20) and the file is encrypted — just not with the
                // cipher §14.2 specifies, so the next open fails with
                // SQLITE_NOTADB and looks like corruption.
                statement.execute("PRAGMA cipher = 'sqlcipher'")
                statement.execute("PRAGMA rekey = ${rawKeySqlLiteral(key)}")
            }
        }

        // Prove the rewrite before destroying the only readable copy.
        DriverManager.getConnection("jdbc:sqlite:${working.absolutePath}", keyProperties(key))
            .use { it.createStatement().use { s -> s.executeQuery("SELECT 1 FROM sqlite_master") } }
        check(!LocalDatabaseGuard.isCleartext(fileHeader(working))) {
            "rekey left ${working.name} readable without a key; refusing to install it"
        }

        Files.move(
            working.toPath(),
            file.toPath(),
            StandardCopyOption.REPLACE_EXISTING,
            StandardCopyOption.ATOMIC_MOVE,
        )
        // Journals belonging to the cleartext file. Left behind they are
        // plaintext pages sitting next to an encrypted database, and SQLite
        // would try to replay them into it.
        File(file.parentFile, file.name + "-wal").delete()
        File(file.parentFile, file.name + "-shm").delete()
        // Deleting does not erase the blocks — §14.6 says so plainly rather
        // than implying the plaintext is gone. Only a factory reset closes that.
    }

    private companion object {
        /**
         * The 32 bytes as SQLCipher's raw key rather than as a passphrase.
         *
         * `withRawUnsaltedKey` renders `x'<hex>'`, which SQLCipher takes
         * literally; `withHexKey` would render bare hex and run 256,000 PBKDF2
         * iterations over it. Measured on this driver: 1 ms to open against
         * 156 ms. The key is already 256 uniformly random bits, so those
         * iterations buy no entropy — only startup time on the hardware that
         * has least of it (§14.2).
         */
        fun keyProperties(key: DatabaseKey): Properties =
            SQLiteMCSqlCipherConfig.getDefault()
                .withRawUnsaltedKey(key.bytes)
                .build()
                .toProperties()

        /**
         * The same raw key as a SQL string literal, for the pragmas that take
         * one. `x'ab..'` with its quotes doubled, so the value SQLite sees is
         * the eight-plus-character string `x'ab..'` and not a blob literal.
         */
        fun rawKeySqlLiteral(key: DatabaseKey): String = "'x''${key.hex()}'''"

        fun fileHeader(file: File): ByteArray? {
            if (!file.isFile) return null
            return file.inputStream().use { stream ->
                val header = ByteArray(LocalDatabaseGuard.CLEARTEXT_HEADER.size)
                val read = stream.readNBytes(header, 0, header.size)
                if (read < header.size) null else header
            }
        }

        fun defaultPath(): String {
            val dir = File(System.getProperty("user.home"), ".dcp")
            dir.mkdirs()
            return File(dir, "dcp.db").absolutePath
        }
    }
}
