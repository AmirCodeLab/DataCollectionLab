package com.dcp.core.security

import java.security.SecureRandom

/**
 * Desktop: the local database key lives in the OS credential store — macOS
 * Keychain, Windows Credential Manager, or the Linux Secret Service
 * (encryption envelope §14.4).
 *
 * Unlike Android's, these stores hand the bytes back, so the key is stored
 * rather than derived. Unlike Android's, they also unlock with the user's
 * session, which is where desktop's app lock comes from (§14.7): if the user
 * has not signed in, or locks the login keychain, the store refuses and the
 * application has no database.
 *
 * The store is a constructor parameter so tests can supply one that is not the
 * developer's real keychain — a test that wrote 32 bytes into someone's login
 * keychain on every run would be its own small vulnerability.
 */
actual class DatabaseKeyStore(
    private val credentials: CredentialStore = CredentialStore.forCurrentOs(),
    private val service: String = SERVICE,
    private val account: String = ACCOUNT,
) {

    actual fun loadOrCreate(): DatabaseKey {
        existing()?.let { return it }

        // Not SecureRandom() — SecureRandom.getInstanceStrong() blocks on Linux
        // when the entropy pool is cold, which on a fresh VM means hanging at
        // startup. The default is a seeded CSPRNG on every JDK we ship on and
        // is the right choice for a 256-bit key.
        val fresh = ByteArray(DatabaseKey.SIZE_BYTES).also { SecureRandom().nextBytes(it) }
        try {
            credentials.write(service, account, fresh)
        } finally {
            fresh.fill(0)
        }

        // Read back rather than returning what was generated. If the store
        // silently dropped the write, the alternative is a working session
        // followed by a database that never opens again.
        return existing() ?: throw DatabaseKeyUnavailable(
            "wrote the local database key to ${credentials.description} but could not read it " +
                "back. Refusing to open an unencrypted database (encryption envelope §14.5).",
        )
    }

    actual fun exists(): Boolean = credentials.read(service, account) != null

    actual fun destroy() {
        credentials.delete(service, account)
    }

    private fun existing(): DatabaseKey? {
        val stored = credentials.read(service, account) ?: return null
        if (stored.size != DatabaseKey.SIZE_BYTES) {
            throw DatabaseKeyUnavailable(
                "the local database key in ${credentials.description} is ${stored.size} bytes, " +
                    "not ${DatabaseKey.SIZE_BYTES}. Refusing to guess: replacing it would make " +
                    "the existing database permanently unreadable (§14.3).",
            )
        }
        return try {
            DatabaseKey(stored)
        } finally {
            stored.fill(0)
        }
    }

    companion object {
        const val SERVICE: String = "com.dcp.local-database"
        const val ACCOUNT: String = "default"
    }
}
