package com.dcp.core.security

/**
 * The platform keystore holding — or deriving — this device's local database
 * key (encryption envelope §14.4).
 *
 * | Platform | Store | Binding |
 * |---|---|---|
 * | Android | Android Keystore, TEE- or StrongBox-backed | a non-exportable HMAC key; the database key is **derived** from it, so nothing is persisted outside the keystore |
 * | iOS | Keychain | 32 bytes, `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` |
 * | Desktop | macOS Keychain, Windows Credential Manager, Linux Secret Service | 32 bytes |
 *
 * Each platform's actual takes its own constructor arguments — Android needs
 * nothing, desktop takes the credential store to use — following
 * [com.dcp.core.sync.DatabaseDriverFactory].
 *
 * There is no in-memory or file-backed implementation on any shipping platform.
 * A fallback would be used, and the first time it were used the database would
 * be readable by whoever picked up the phone (§14.5).
 */
expect class DatabaseKeyStore {

    /**
     * The device's database key, generating it on first run.
     *
     * @throws DatabaseKeyUnavailable if the keystore is absent, refuses, or the
     *   app lock was not satisfied. Never returns a key it invented itself.
     */
    fun loadOrCreate(): DatabaseKey

    /** Whether a key already exists — i.e. whether this is the first run. */
    fun exists(): Boolean

    /**
     * Forgets the key. **This makes the local database permanently
     * unreadable** (§14.3: there is no recovery). Only for an explicit
     * "erase this device's data" action and for tests.
     */
    fun destroy()
}
