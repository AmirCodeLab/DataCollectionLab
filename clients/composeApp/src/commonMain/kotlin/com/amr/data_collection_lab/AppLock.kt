package com.amr.data_collection_lab

/**
 * The optional app lock of encryption envelope §14.7.
 *
 * When on, the platform keystore releases the local database key only after a
 * device credential or a strong biometric. The lock gates **the key**, not a
 * screen: a lock that only hid the UI would protect nothing, because the
 * database file is still there to be copied off the device.
 *
 * What each platform does with it:
 *
 * | Platform | With the lock on |
 * |---|---|
 * | Android | the keystore key is generated with `setUserAuthenticationRequired`, satisfied by a device unlock within [DatabaseKeyStore.DEFAULT_AUTH_VALIDITY_SECONDS]; a stale one fails the key read and the app says so |
 * | iOS | the Keychain item carries `kSecAccessControlUserPresence`, so iOS itself raises the Face ID / Touch ID / passcode prompt when the key is read |
 * | Desktop | the OS credential store's own unlock — login keychain, Windows sign-in, keyring prompt |
 *
 * **It is a constant, and that is a real limitation, not an oversight.** On
 * Android the requirement is baked into the keystore key at generation, and on
 * iOS into the Keychain item's access control; neither can be changed
 * afterwards. Turning the lock on or off on a device that already holds data
 * therefore means generating a second key and re-keying the database under it
 * (`PRAGMA rekey`), and **that is not implemented**. A settings toggle that
 * silently made every existing answer unreadable would be worse than no toggle,
 * so there is not one yet.
 *
 * Until the re-key lands, this is chosen per build. Changing it and reinstalling
 * over an existing device would leave a database whose key no longer exists —
 * `createSubmissionStore` refuses that case loudly (§14.3) rather than replacing
 * the database.
 */
object AppLock {

    /**
     * Off by default. Turning it on requires every device in the deployment to
     * have a lock screen set: without one, Android has nothing to bind the key
     * to and key generation fails, which by §14.5 means the app does not start.
     */
    const val ENABLED: Boolean = false
}
