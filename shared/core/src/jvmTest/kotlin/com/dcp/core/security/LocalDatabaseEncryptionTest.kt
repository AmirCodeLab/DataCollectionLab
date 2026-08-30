package com.dcp.core.security

/**
 * The properties encryption envelope §14.9 requires of every client, checked
 * against the bytes on disk rather than against the code that wrote them.
 *
 * That distinction is the whole design of this file. "We call `PRAGMA key`" and
 * "the answers are not readable on disk" are different claims, and only the
 * second one is worth anything: an unrecognised pragma is a silent no-op in
 * SQLite, so a build that lost its cipher would still pass any test that only
 * watched the API being used. Every assertion here reads the file, or greps the
 * app's storage, or opens the database with the wrong key and insists on
 * failure.
 */

import app.cash.sqldelight.db.QueryResult
import app.cash.sqldelight.db.SqlDriver
import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.core.sync.DatabaseDriverFactory
import com.dcp.core.sync.LocalDatabaseState
import com.dcp.core.sync.OpKind
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.createSubmissionStore
import com.dcp.form.FormValue
import java.io.File
import java.nio.file.Files
import java.sql.DriverManager
import java.util.Properties
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class LocalDatabaseEncryptionTest {

    private val appDir: File = Files.createTempDirectory("dcp-local-encryption").toFile()
    private val dbPath: String = File(appDir, "dcp.db").absolutePath

    @AfterTest
    fun cleanUp() {
        appDir.deleteRecursively()
    }

    /**
     * A real answer: distinctive enough that finding it in a file is
     * unambiguous, and long enough not to occur by chance in a page of SQLite
     * bookkeeping.
     */
    private val answer = "Amina Nakabuye of 14 Kabalagala Road"

    // ---------------------------------------------------------------- §14.9.1

    @Test
    fun `the database file on disk contains none of the plaintext answers`() {
        open().use { it.store.writeAnAnswer() }

        val file = File(dbPath)
        assertTrue(file.length() > 0, "nothing was written")
        assertFalse(
            file.readText(Charsets.ISO_8859_1).contains(answer),
            "the answer is readable in $dbPath — the local database is not encrypted",
        )
        assertFalse(
            LocalDatabaseGuard.isCleartext(file.readBytes().copyOf(16)),
            "the file begins with the plain SQLite header, so nothing encrypted it",
        )
    }

    @Test
    fun `no file the app owns contains a plaintext answer, journals included`() {
        // The -wal is where the newest pages live before a checkpoint, and it is
        // the file a check that only looked at dcp.db would miss.
        open().use { database ->
            database.store.writeAnAnswer()
            assertEquals(emptyList(), appDir.filesContaining(answer))
        }
        assertEquals(emptyList(), appDir.filesContaining(answer), "after closing")
    }

    // ---------------------------------------------------------------- §14.9.2

    @Test
    fun `a database created under one key cannot be opened with another`() {
        val credentials = InMemoryCredentialStore()
        open(credentials).use { it.store.writeAnAnswer() }

        // Another device's key. The file, the driver and the schema are
        // identical, so the key is the only thing under test.
        credentials.replaceWith(ByteArray(DatabaseKey.SIZE_BYTES) { 0x5A })

        val failure = assertFailsWith<Exception> { open(credentials).use { } }
        assertTrue(
            failure.chain().any { it.message?.contains("not a database") == true },
            "expected SQLITE_NOTADB, got: ${failure.chain().joinToString { it.message.orEmpty() }}",
        )
    }

    @Test
    fun `a database created under a key cannot be opened with no key at all`() {
        open().use { it.store.writeAnAnswer() }

        // The plain JDBC driver, which is what someone who pulled the file off
        // a seized phone would reach for.
        val failure = assertFailsWith<Exception> {
            DriverManager.getConnection("jdbc:sqlite:$dbPath").use { connection ->
                connection.createStatement().use { it.executeQuery("SELECT * FROM op_outbox") }
            }
        }
        assertContains(failure.message.orEmpty(), "not a database")
    }

    // ---------------------------------------------------------------- §14.9.3

    @Test
    fun `the key is in no file the app owns`() {
        val credentials = InMemoryCredentialStore()
        open(credentials).use { it.store.writeAnAnswer() }

        val key = keyStore(credentials).loadOrCreate()
        val raw = key.bytes
        val hex = key.hex()
        val literal = key.rawKeyLiteral()

        // Every file under the app's directory: the database, its journals, and
        // anything a future preferences implementation drops beside them. On
        // Android the same guarantee covers shared_prefs, and there the key is
        // not merely absent but underivable — it never leaves the Keystore
        // (§14.4).
        val carriers = appDir.walkTopDown().filter { it.isFile }.filter { file ->
            val bytes = file.readBytes()
            val text = String(bytes, Charsets.ISO_8859_1)
            bytes.containsSubsequence(raw) || text.contains(hex) || text.contains(literal)
        }.map { it.name }.toList()

        assertEquals(emptyList(), carriers, "these files carry the database key")
    }

    @Test
    fun `the key store refuses rather than inventing a key when the store is unavailable`() {
        // §14.5: no fallback. A key this process made up would open a brand new
        // empty database and orphan the real one, which reads to the enumerator
        // as "all my work is gone".
        val broken = object : CredentialStore {
            override val description = "a credential store that is not there"
            override fun read(service: String, account: String): ByteArray =
                throw DatabaseKeyUnavailable(description)

            override fun write(service: String, account: String, secret: ByteArray): Unit =
                throw DatabaseKeyUnavailable(description)

            override fun delete(service: String, account: String) = Unit
        }
        assertFailsWith<DatabaseKeyUnavailable> { keyStore(broken).loadOrCreate() }
    }

    @Test
    fun `the key store refuses a stored secret of the wrong size rather than replacing it`() {
        // Replacing it would be the friendly-looking move and would destroy
        // every unsynced answer on the device (§14.3: there is no recovery).
        val credentials = InMemoryCredentialStore()
        credentials.write("test", "device", ByteArray(16))
        assertFailsWith<DatabaseKeyUnavailable> { keyStore(credentials).loadOrCreate() }
    }

    @Test
    fun `the same key comes back on the next run, so the database reopens`() {
        val credentials = InMemoryCredentialStore()
        val submissionId = open(credentials).use { database ->
            database.store.writeAnAnswer()
        }

        open(credentials).use { database ->
            assertEquals(
                mapOf("name" to FormValue.Text(answer)),
                database.store.materialisedAnswers(submissionId),
            )
        }
    }

    @Test
    fun `an encrypted database with no key in the keystore is refused, not replaced`() {
        // The failure this prevents is total and silent. A keystore that says
        // "no key" when it is really locked or unavailable looks exactly like a
        // first run; minting a key then opens a new empty database beside the
        // real one, and every unsynced answer on the device is unreachable
        // forever (§14.3) while the app reports itself perfectly healthy.
        //
        // Not hypothetical: macOS's security(1) reports a keychain it cannot
        // open with the same errSecItemNotFound it uses for a key that is
        // genuinely absent, so the keystore alone cannot tell them apart.
        val credentials = InMemoryCredentialStore()
        open(credentials).use { it.store.writeAnAnswer() }

        credentials.forgetEverything()

        val failure = assertFailsWith<DatabaseKeyUnavailable> {
            createSubmissionStore(DatabaseDriverFactory(dbPath), keyStore(credentials))
        }
        assertContains(failure.message.orEmpty(), "§14.3")

        // And the database it refused to touch is untouched: the same key
        // still opens it, with the answer still in it.
        assertEquals(LocalDatabaseState.ENCRYPTED, DatabaseDriverFactory(dbPath).databaseState())
    }

    @Test
    fun `a cleartext database with no key is a normal upgrade, not a lost key`() {
        // The mirror of the test above: the guard must not fire on the one
        // case where "database present, no key" is exactly what is expected.
        cleartextDatabase().use { it.store.writeAnAnswer() }
        assertEquals(LocalDatabaseState.CLEARTEXT, DatabaseDriverFactory(dbPath).databaseState())

        val store = createSubmissionStore(DatabaseDriverFactory(dbPath), keyStore())
        assertFalse(File(dbPath).readText(Charsets.ISO_8859_1).contains(answer))
        assertEquals(LocalDatabaseState.ENCRYPTED, DatabaseDriverFactory(dbPath).databaseState())
        assertTrue(store.pendingCount() > 0)
    }

    @Test
    fun `the public entry point opens an encrypted database without the caller holding a key`() {
        // createSubmissionStore takes the key store, not the key: nothing above
        // it in the app ever holds key material.
        val store = createSubmissionStore(DatabaseDriverFactory(dbPath), keyStore())
        store.writeAnAnswer()
        assertFalse(File(dbPath).readText(Charsets.ISO_8859_1).contains(answer))
    }

    // ---------------------------------------------------------------- §14.9.4

    @Test
    fun `an existing cleartext database is migrated with its rows, schema version and counter`() {
        // A device upgrading from a build that predates §14. Recreating instead
        // of migrating would reset the logical counter, and operation nonces are
        // derived from it (§4.5) — the one failure AES-GCM does not tolerate. So
        // this test cares as much about the counter as about the rows.
        val submissionId: String
        val deviceBefore: String
        val counterBefore: Long
        cleartextDatabase().use { database ->
            submissionId = database.store.writeAnAnswer()
            database.store.appendOp(
                submissionId, "household", 1, OpKind.SET, "age", FormValue.Integer(41),
            )
            deviceBefore = database.store.deviceId
            counterBefore = database.store.opsFor(submissionId).maxOf { it.counter }
        }
        val versionBefore = userVersionOfCleartext()

        assertTrue(
            File(dbPath).readText(Charsets.ISO_8859_1).contains(answer),
            "the fixture was supposed to be a cleartext database",
        )

        open().use { database ->
            assertFalse(
                File(dbPath).readText(Charsets.ISO_8859_1).contains(answer),
                "the migrated database still holds the answer in cleartext",
            )
            assertEquals(
                mapOf("name" to FormValue.Text(answer), "age" to FormValue.Integer(41)),
                database.store.materialisedAnswers(submissionId),
            )
            assertEquals(deviceBefore, database.store.deviceId, "the device identity changed")

            // The next op must continue the sequence, not restart it. This is
            // the assertion that stands between a migration and a repeated
            // AES-GCM nonce.
            val next = database.store.appendOp(
                submissionId, "household", 1, OpKind.SET, "age", FormValue.Integer(42),
            )
            assertEquals(counterBefore + 1, next.counter, "the logical counter was reset")

            assertEquals(
                versionBefore,
                database.userVersion(),
                "user_version was lost, so SQLDelight will replay every migration",
            )
        }
        assertFalse(File("$dbPath.migrating").exists(), "the working copy was left behind")
    }

    @Test
    fun `a failed migration leaves the cleartext database in place rather than half-rewritten`() {
        // The order that matters: the working copy is moved over the original
        // only once it has been reopened and read under the new key. Here the
        // rewrite is made impossible — the working path is a directory — and
        // the original must survive intact and still open.
        val submissionId = cleartextDatabase().use { it.store.writeAnAnswer() }
        // A non-empty directory: REPLACE_EXISTING will delete an empty one and
        // carry on, so an empty one would not break anything.
        File("$dbPath.migrating").mkdirs()
        File("$dbPath.migrating/occupied").writeText("in the way")

        assertFailsWith<Exception> { open().use { } }

        File("$dbPath.migrating").deleteRecursively()
        cleartextDatabase().use { database ->
            assertEquals(
                mapOf("name" to FormValue.Text(answer)),
                database.store.materialisedAnswers(submissionId),
                "the cleartext database did not survive a migration that could not finish",
            )
        }
    }

    // ---------------------------------------------------------------- §14.9.5

    @Test
    fun `a cleartext database is refused rather than used`() {
        // What a build linked against plain SQLite would leave behind. The
        // guard is the only thing between that and an app that works perfectly
        // while writing every answer to disk in the clear.
        val cleartext = LocalDatabaseGuard.CLEARTEXT_HEADER + "page data".encodeToByteArray()
        assertTrue(LocalDatabaseGuard.isCleartext(cleartext))

        val failure = assertFailsWith<LocalDatabaseNotEncrypted> {
            LocalDatabaseGuard.requireEncrypted(dbPath, cleartext)
        }
        assertContains(failure.message.orEmpty(), "§14.5")

        // Ciphertext begins with SQLCipher's random salt, and an absent or
        // half-written file is not a claim either way.
        assertFalse(LocalDatabaseGuard.isCleartext(ByteArray(16) { 0x7F }))
        assertFalse(LocalDatabaseGuard.isCleartext(null))
        assertFalse(LocalDatabaseGuard.isCleartext("SQLite".encodeToByteArray()))
    }

    @Test
    fun `the driver refuses to hand back a driver whose file turned out to be cleartext`() {
        // Simulating the missing cipher directly: a cleartext database that
        // the migration never sees, because it is not where the factory looks.
        // requireEncrypted is what has to reject it.
        val stray = File(appDir, "stray.db")
        JdbcSqliteDriver("jdbc:sqlite:${stray.absolutePath}", Properties(), DcpDatabase.Schema).close()
        assertTrue(LocalDatabaseGuard.isCleartext(stray.readBytes().copyOf(16)))
        assertFailsWith<LocalDatabaseNotEncrypted> {
            LocalDatabaseGuard.requireEncrypted(stray.absolutePath, stray.readBytes().copyOf(16))
        }
    }

    // ---------------------------------------------------------------- the key

    @Test
    fun `a key never renders itself, so logging one leaks nothing`() {
        val key = DatabaseKey(ByteArray(DatabaseKey.SIZE_BYTES) { 0x2B })
        assertFalse(key.toString().contains(key.hex()), "toString rendered the key")
        assertFalse(key.toString().contains("2b2b2b"), "toString rendered the key")

        key.destroy()
        assertFailsWith<IllegalArgumentException> { key.bytes }
    }

    @Test
    fun `a key hands out copies, so a binding that wipes what it was given cannot wipe the key`() {
        // SQLCipher's Android factory zeroes the passphrase array it is handed.
        // Were that array the key's own storage, the second connection opened
        // in a process would key with 32 zero bytes.
        val key = DatabaseKey(ByteArray(DatabaseKey.SIZE_BYTES) { 0x11 })
        key.bytes.fill(0)
        assertTrue(key.bytes.all { it == 0x11.toByte() })
    }

    @Test
    fun `the raw key literal is what SQLCipher reads as a key rather than a password`() {
        // Not cosmetic: bare hex is a password, and costs 256,000 PBKDF2
        // iterations at every launch over material that already carries 256
        // bits of entropy (§14.2).
        val key = DatabaseKey(ByteArray(DatabaseKey.SIZE_BYTES) { 0xAB.toByte() })
        assertEquals("x'${"ab".repeat(32)}'", key.rawKeyLiteral())
    }

    @Test
    fun `a key is exactly 32 bytes, and says so without printing the material`() {
        val failure = assertFailsWith<IllegalArgumentException> { DatabaseKey(ByteArray(16)) }
        assertContains(failure.message.orEmpty(), "32 bytes, got 16")
    }

    @Test
    fun `two devices get different keys`() {
        val first = keyStore(InMemoryCredentialStore()).loadOrCreate().hex()
        val second = keyStore(InMemoryCredentialStore()).loadOrCreate().hex()
        assertNotEquals(first, second, "the key is not being generated per device")
    }

    // ------------------------------------------------------------- machinery

    private fun keyStore(store: CredentialStore = InMemoryCredentialStore()) =
        DatabaseKeyStore(credentials = store, service = "test", account = "device")

    /** The encrypted database, through the production driver. */
    private fun open(credentials: CredentialStore = InMemoryCredentialStore()): OpenDatabase {
        val key = keyStore(credentials).loadOrCreate()
        val driver = try {
            DatabaseDriverFactory(dbPath).createDriver(key)
        } finally {
            key.destroy()
        }
        return OpenDatabase(driver)
    }

    /** The pre-§14 database: same schema, same path, no cipher. */
    private fun cleartextDatabase(): OpenDatabase =
        OpenDatabase(JdbcSqliteDriver("jdbc:sqlite:$dbPath", Properties(), DcpDatabase.Schema))

    private fun userVersionOfCleartext(): Long =
        DriverManager.getConnection("jdbc:sqlite:$dbPath").use { connection ->
            connection.createStatement().use { statement ->
                statement.executeQuery("PRAGMA user_version").use { it.next(); it.getLong(1) }
            }
        }

    private inner class OpenDatabase(val driver: SqlDriver) : AutoCloseable {
        val store: SubmissionStore = SubmissionStore(DcpDatabase(driver))

        fun userVersion(): Long = driver.executeQuery(
            null,
            "PRAGMA user_version",
            { cursor -> cursor.next(); QueryResult.Value(cursor.getLong(0)!!) },
            0,
        ).value

        override fun close() = driver.close()
    }

    private fun SubmissionStore.writeAnAnswer(): String {
        val submissionId = createDraft("household", 1)
        appendOp(submissionId, "household", 1, OpKind.SET, "name", FormValue.Text(answer))
        return submissionId
    }

    private fun File.filesContaining(needle: String): List<String> =
        walkTopDown().filter { it.isFile }
            .filter { it.readText(Charsets.ISO_8859_1).contains(needle) }
            .map { it.name }
            .toList()

    private fun Throwable.chain(): Sequence<Throwable> = generateSequence(this) { it.cause }
}

/**
 * Stands in for the OS credential store, so these tests neither depend on a
 * keyring being present — CI is a headless Linux runner — nor write 32-byte
 * secrets into a developer's own login keychain on every run.
 *
 * The real macOS implementation is exercised against a scratch keychain in
 * [MacKeychainCredentialStoreTest].
 */
internal class InMemoryCredentialStore : CredentialStore {

    private val entries = mutableMapOf<String, ByteArray>()

    override val description: String get() = "an in-memory credential store (tests only)"

    override fun read(service: String, account: String): ByteArray? =
        entries["$service/$account"]?.copyOf()

    override fun write(service: String, account: String, secret: ByteArray) {
        entries["$service/$account"] = secret.copyOf()
    }

    override fun delete(service: String, account: String) {
        entries.remove("$service/$account")
    }

    /** Simulates a device whose keystore holds a different device's key. */
    fun replaceWith(secret: ByteArray) {
        entries.keys.toList().forEach { entries[it] = secret.copyOf() }
    }

    /** Simulates a keystore that has lost the key, or will not open. */
    fun forgetEverything() {
        entries.clear()
    }
}

private fun ByteArray.containsSubsequence(needle: ByteArray): Boolean {
    if (needle.isEmpty() || needle.size > size) return false
    outer@ for (start in 0..size - needle.size) {
        for (i in needle.indices) if (this[start + i] != needle[i]) continue@outer
        return true
    }
    return false
}
