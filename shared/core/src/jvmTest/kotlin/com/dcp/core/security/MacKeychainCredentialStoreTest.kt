package com.dcp.core.security

/**
 * The macOS half of §14.4, against a real Keychain.
 *
 * [InMemoryCredentialStore] proves the key store's logic and proves nothing
 * about the store underneath it — whether `security(1)` is invoked correctly,
 * whether "no such item" is told apart from "the keychain refused", whether the
 * secret survives a round trip byte for byte. Those only come out against the
 * real thing.
 *
 * It runs against a scratch keychain created and destroyed by the test, never
 * the developer's login keychain: a test that wrote a 32-byte secret into
 * someone's real keychain on every run would be its own small vulnerability,
 * and one that could not run unattended because the login keychain prompts.
 *
 * Skipped off macOS, which includes CI. The Linux (`secret-tool`) and Windows
 * (Credential Manager) stores have no equivalent here — a headless runner has
 * no Secret Service daemon — and that gap is recorded in
 * `docs/known-breaks.md` rather than papered over.
 */

import java.io.File
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class MacKeychainCredentialStoreTest {

    private val onMac = System.getProperty("os.name").orEmpty().lowercase().contains("mac")
    private val scratchDir: File = Files.createTempDirectory("dcp-keychain").toFile()
    private val keychain: String = File(scratchDir, "dcp-test.keychain-db").absolutePath
    private val service = "com.dcp.local-database.test"
    private val account = "device-under-test"

    private fun store() = MacKeychainCredentialStore(keychain = keychain)

    private fun createKeychain() {
        runCapturing(listOf("security", "create-keychain", "-p", "dcp-test", keychain))
        runCapturing(listOf("security", "unlock-keychain", "-p", "dcp-test", keychain))
        // Otherwise the keychain relocks on a timer mid-test.
        runCapturing(listOf("security", "set-keychain-settings", keychain))
    }

    @AfterTest
    fun cleanUp() {
        if (onMac) runCapturing(listOf("security", "delete-keychain", keychain))
        scratchDir.deleteRecursively()
    }

    @Test
    fun `a key round-trips through the macOS Keychain byte for byte`() {
        if (!onMac) return
        createKeychain()

        val secret = ByteArray(DatabaseKey.SIZE_BYTES) { (it * 7 + 3).toByte() }
        val store = store()

        // Absent means null, not an exception. Getting this wrong the other way
        // turns "first run" into a crash, or worse, turns "the keychain is
        // locked" into "no key yet" and mints a second key over a database that
        // the first one opened (§14.3: there is no recovery).
        assertNull(store.read(service, account))

        store.write(service, account, secret)
        assertContentEquals(secret, store.read(service, account))

        // The bytes must survive high values and zeroes, which is why they go
        // through as hex rather than as text.
        val awkward = ByteArray(DatabaseKey.SIZE_BYTES).also {
            it[0] = 0
            it[1] = 0xFF.toByte()
            it[2] = 0x0A
            it[3] = 0x27 // an apostrophe, which the security(1) command quotes
        }
        store.write(service, account, awkward)
        assertContentEquals(awkward, store.read(service, account))

        store.delete(service, account)
        assertNull(store.read(service, account))
    }

    @Test
    fun `the key store built on the real Keychain generates once and returns the same key`() {
        if (!onMac) return
        createKeychain()

        val keyStore = DatabaseKeyStore(store(), service, account)
        val first = keyStore.loadOrCreate()
        assertTrue(keyStore.exists())
        val second = keyStore.loadOrCreate()

        assertContentEquals(first.bytes, second.bytes, "a second run generated a different key")
        assertTrue(first.bytes.any { it != 0.toByte() }, "the key is all zeroes")

        keyStore.destroy()
        assertTrue(!keyStore.exists())
    }

    @Test
    fun `a keychain that is not there reads as absent, which is why it is not the only guard`() {
        if (!onMac) return

        // Documenting a real limitation rather than asserting a guarantee.
        // `security(1)` answers *everything* that is not a hit with
        // errSecItemNotFound (exit 44): a missing keychain, a keychain that is
        // not a keychain, an item that genuinely is not there. So the store
        // cannot tell "first run" from "this keychain will not open", and a
        // locked keychain does not even get that far — it asks a person, which
        // is why runCapturing bounds the wait.
        val missing = MacKeychainCredentialStore(
            keychain = File(scratchDir, "no-such.keychain-db").absolutePath,
        )
        assertNull(missing.read(service, account))

        // Because that distinction is unavailable here, the guard against
        // silently minting a key over an existing database lives one level up,
        // in createSubmissionStore, and keys off the database file itself:
        // encrypted database + no key is a lost key, not a first run. See
        // LocalDatabaseEncryptionTest.
    }
}
